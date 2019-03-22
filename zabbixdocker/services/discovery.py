from __future__ import division

import datetime
import json
import logging
import os
import queue
import re
import threading

import pyzabbix


class DockerDiscoveryService(threading.Thread):
    """This class implements the discovery service which discovers containers and images"""

    def __init__(self, config, stop_event, docker_client, zabbix_sender):
        """Initialize a new instance"""

        super(DockerDiscoveryService, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._workers = []
        self._containers_queue = queue.Queue()
        self._config = config
        self._stop_event = stop_event
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender

    def run(self):
        """Execute the thread"""

        if self._config.getboolean("main", "containers"):
            worker = DockerDiscoveryContainersWorker(self._config, self._docker_client, self._zabbix_sender,
                                                     self._containers_queue)
            worker.setDaemon(True)
            self._workers.append(worker)

        if self._config.getboolean("discovery", "poll_events"):
            worker = DockerDiscoveryContainersEventsPollerWorker(self._config, self._docker_client, self)
            worker.setDaemon(True)
            self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("discovery", "startup") > 0:
            self._stop_event.wait(self._config.getint("discovery", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self.execute_containers_discovery()

            if self._stop_event.wait(self._config.getint("discovery", "interval")):
                break

        self._logger.info("service stopped")

    def execute(self):
        """Execute the service"""

        self._logger.debug("requesting discovery")
        self._containers_queue.put("discovery")

    def execute_containers_discovery(self):
        """Execute the service"""

        self._logger.debug("requesting containers discovery")
        self._containers_queue.put("discovery")


class DockerDiscoveryContainersWorker(threading.Thread):
    """This class implements a containers discovery worker thread"""

    def __init__(self, config, docker_client, zabbix_sender, containers_queue):
        """Initialize the thread"""

        super(DockerDiscoveryContainersWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._containers_queue = containers_queue

    def run(self):
        """Execute the thread"""

        while True:
            self._logger.debug("waiting execution queue")
            item = self._containers_queue.get()
            if item is None:
                break

            self._logger.info("starting containers discovery")

            try:
                metrics = []
                discovery_containers = []
                discovery_containers_stats = []
                discovery_containers_stats_cpus = []
                discovery_containers_stats_networks = []
                discovery_containers_stats_devices = []
                discovery_containers_top = []
                device_pattern = re.compile(r'^DEVNAME=(.+)$')

                containers = self._docker_client.containers(all=True)

                for container in containers:
                    container_id = container["Id"]
                    container_name = container["Names"][0][1:]

                    discovery_containers.append({
                        "{#NAME}": container_name
                    })

                    if container["Status"].startswith("Up"):
                        if self._config.getboolean("main", "containers_stats"):
                            container_stats = self._docker_client.stats(container_id, decode=True, stream=False)

                            discovery_containers_stats.append({
                                "{#NAME}": container_name
                            })

                            if (
                                "cpu_stats" in container_stats and
                                "cpu_usage" in container_stats["cpu_stats"] and
                                "percpu_usage" in container_stats["cpu_stats"]["cpu_usage"]
                            ):
                                cpus = len(container_stats["cpu_stats"]["cpu_usage"]["percpu_usage"])

                                for i in range(cpus):
                                    discovery_containers_stats_cpus.append({
                                        "{#NAME}": container_name,
                                        "{#CPU}": "%d" % i
                                    })

                            if "networks" in container_stats:
                                for container_stats_network_ifname in list(container_stats["networks"].keys()):
                                    discovery_containers_stats_networks.append({
                                        "{#NAME}": container_name,
                                        "{#IFNAME}": container_stats_network_ifname
                                    })

                            if (
                                "blkio_stats" in container_stats and
                                "io_serviced_recursive" in container_stats["blkio_stats"]
                            ):
                                for j in range(len(container_stats["blkio_stats"]["io_serviced_recursive"])):
                                    if container_stats["blkio_stats"]["io_serviced_recursive"][j]["op"] != "Total":
                                        continue

                                    sysfs_file = "%s/dev/block/%s:%s/uevent" % (
                                        os.path.join(self._config.get("main", "rootfs"), "sys"),
                                        container_stats["blkio_stats"]["io_serviced_recursive"][j]["major"],
                                        container_stats["blkio_stats"]["io_serviced_recursive"][j]["minor"])
                                    with open(sysfs_file) as f:
                                        for line in f:
                                            match = re.search(device_pattern, line)
                                            if not match:
                                                continue

                                            discovery_containers_stats_devices.append({
                                                "{#NAME}": container_name,
                                                "{#DEVMAJOR}": container_stats["blkio_stats"]
                                                ["io_serviced_recursive"][j]["major"],
                                                "{#DEVMINOR}": container_stats["blkio_stats"]
                                                ["io_serviced_recursive"][j]["minor"],
                                                "{#DEVNAME}": match.group(1)
                                            })

                        if self._config.getboolean("main", "containers_top"):
                            container_top = self._docker_client.top(container)
                            if "Processes" in container_top:
                                for j in range(len(container_top["Processes"])):
                                    discovery_containers_top.append({
                                        "{#NAME}": container_name,
                                        "{#PID}": container_top["Processes"][j][1],
                                        "{#CMD}": container_top["Processes"][j][7]
                                    })

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.discovery.containers",
                        json.dumps({"data": discovery_containers})))

                if self._config.getboolean("main", "containers_stats"):
                    metrics.append(
                        pyzabbix.ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.discovery.containers.stats",
                            json.dumps({"data": discovery_containers_stats})))

                    metrics.append(
                        pyzabbix.ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.discovery.containers.stats.cpus",
                            json.dumps({"data": discovery_containers_stats_cpus})))

                    metrics.append(
                        pyzabbix.ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.discovery.containers.stats.networks",
                            json.dumps({"data": discovery_containers_stats_networks})))

                    metrics.append(
                        pyzabbix.ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.discovery.containers.stats.devices",
                            json.dumps({"data": discovery_containers_stats_devices})))

                if self._config.getboolean("main", "containers_top"):
                    metrics.append(
                        pyzabbix.ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.discovery.containers.top",
                            json.dumps({"data": discovery_containers_top})))

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send containers discovery metrics")


class DockerDiscoveryContainersEventsPollerWorker(threading.Thread):
    """This class implements a containers discovery by events worker thread"""

    def __init__(self, config, docker_client, discovery_service):
        """Initialize the thread"""

        super(DockerDiscoveryContainersEventsPollerWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._discovery_service = discovery_service

    def run(self):
        """Execute the thread"""

        until = None

        while True:
            since = datetime.datetime.utcnow() if until is None else until
            until = datetime.datetime.utcnow() + \
                datetime.timedelta(seconds=self._config.getint("discovery", "poll_events_interval"))

            containers_start = 0

            self._logger.info("querying containers events")
            for event in self._docker_client.events(since,
                                                    until,
                                                    {
                                                        "type": "container",
                                                        "event": "start"
                                                    },
                                                    True):
                self._logger.debug("new docker event: %s" % event)

                if event["status"] == "start":
                    containers_start += 1

            if containers_start > 0:
                self._discovery_service.execute_containers_discovery()
