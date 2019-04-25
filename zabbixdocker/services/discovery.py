from __future__ import division
from typing import List, Optional

import configparser
import datetime
import json
import logging
import os
import queue
import re
import threading

import docker

from pyzabbix import ZabbixMetric, ZabbixSender


class DockerDiscoveryService(threading.Thread):
    """ This class implements the service which discovers docker resources """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize an instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerDiscoveryService, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._workers = []
        self._containers_queue = queue.Queue()
        self._config = config
        self._stop_event = stop_event
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender

    def run(self):
        """
        Execute the thread
        """
        worker = DockerDiscoveryWorker(self._config, self._docker_client, self._zabbix_sender,
                                       self._containers_queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        if self._config.getboolean("discovery", "poll_events"):
            worker = DockerDiscoveryEventsPollerWorker(self._config, self._docker_client, self)
            worker.setDaemon(True)
            self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("discovery", "startup") > 0:
            self._stop_event.wait(self._config.getint("discovery", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("discovery", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the discovery
        """
        self._logger.debug("requesting discovery")
        self._containers_queue.put("discovery")

    def trigger(self):
        """
        Request a new discovery execution
        """
        self._logger.debug("triggering discovery execution")
        self._execute()


class DockerDiscoveryWorker(threading.Thread):
    """ This class implements a discovery worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 containers_queue: queue.Queue):
        """
        Initialize the instance

        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param containers_queue: the containers queue
        """
        super(DockerDiscoveryWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._containers_queue = containers_queue

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            item = self._containers_queue.get()
            if item is None:
                break

            self._logger.info("starting discovery")

            try:
                metrics = []

                if self._config.getboolean("main", "containers") is True:
                    m = self._discover_containers()
                    if m is not None:
                        metrics.extend(m)

                if self._config.getboolean("main", "swarm") is True:
                    if self._config.getboolean("main", "swarm_services") is True:
                        m = self._discover_swarm_services()
                        if m is not None:
                            metrics.extend(m)

                    if self._config.getboolean("main", "swarm_stacks") is True:
                        m = self._discover_swarm_stacks()
                        if m is not None:
                            metrics.extend(m)

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send discovery metrics")

    def _discover_containers(self) -> Optional[List[ZabbixMetric]]:
        """
        Discover containers

        :return: the discovery metrics
        """
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
            container_stack = ""
            container_service = ""

            if (
                "com.docker.stack.namespace" in container["Labels"] and
                "com.docker.stack.service.name" in container["Labels"]
            ):
                container_stack = container["Labels"]["com.docker.stack.namespace"]
                container_service = container["Labels"]["com.docker.stack.service.name"]

            discovery_containers.append({
                "{#NAME}": container_name,
                "{#STACK}": container_stack,
                "{#SERVICE}": container_service
            })

            if container["Status"].startswith("Up") is False:
                continue

            if self._config.getboolean("main", "containers_stats"):
                container_stats = self._docker_client.stats(container_id, decode=False, stream=False)

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
            ZabbixMetric(
                self._config.get("zabbix", "hostname"),
                "docker.discovery.containers",
                json.dumps({"data": discovery_containers})))

        if self._config.getboolean("main", "containers_stats"):
            metrics.append(
                ZabbixMetric(
                    self._config.get("zabbix", "hostname"),
                    "docker.discovery.containers.stats",
                    json.dumps({"data": discovery_containers_stats})))

            metrics.append(
                ZabbixMetric(
                    self._config.get("zabbix", "hostname"),
                    "docker.discovery.containers.stats.cpus",
                    json.dumps({"data": discovery_containers_stats_cpus})))

            metrics.append(
                ZabbixMetric(
                    self._config.get("zabbix", "hostname"),
                    "docker.discovery.containers.stats.networks",
                    json.dumps({"data": discovery_containers_stats_networks})))

            metrics.append(
                ZabbixMetric(
                    self._config.get("zabbix", "hostname"),
                    "docker.discovery.containers.stats.devices",
                    json.dumps({"data": discovery_containers_stats_devices})))

        if self._config.getboolean("main", "containers_top"):
            metrics.append(
                ZabbixMetric(
                    self._config.get("zabbix", "hostname"),
                    "docker.discovery.containers.top",
                    json.dumps({"data": discovery_containers_top})))

        return metrics

    def _discover_swarm_services(self) -> Optional[List[ZabbixMetric]]:
        """
        Discover swarm services

        :return: the discovery metrics
        """
        info = self._docker_client.info()

        if (
            "Swarm" not in info or
            info["Swarm"] == "inactive" or
            "NodeID" not in info["Swarm"] or
            info["Swarm"]["NodeID"] == "" or
            "RemoteManagers" not in info["Swarm"] or
            info["Swarm"]["RemoteManagers"] is None
        ):
            self._logger.debug("node is not a swarm member")

            return None

        node_id = info["Swarm"]["NodeID"]
        manager = False

        for remote_manager in info["Swarm"]["RemoteManagers"]:
            if remote_manager["NodeID"] == node_id:
                manager = True

        if manager is False:
            self._logger.debug("node is not a swarm manager")

            return None

        node_info = self._docker_client.inspect_node(node_id)
        leader = False

        if (
            "Leader" in node_info["ManagerStatus"] and
            node_info["ManagerStatus"]["Leader"] is True and
            node_info["ManagerStatus"]["Reachability"] == "reachable"
        ):
            leader = True

        if leader is False:
            self._logger.debug("node is not the swarm leader")

            return None

        metrics = []
        discovery_services = []

        services = self._docker_client.services()

        for service in services:
            service_name = service["Spec"]["Name"]
            service_stack = ""

            if "com.docker.stack.namespace" in service["Spec"]["Labels"]:
                service_stack = service["Spec"]["Labels"]["com.docker.stack.namespace"]

            discovery_services.append({
                "{#NAME}": service_name,
                "{#STACK}": service_stack
            })

        metrics.append(
            ZabbixMetric(
                self._config.get("zabbix", "hostname_cluster"),
                "docker.discovery.swarm.services",
                json.dumps({"data": discovery_services})))

        return metrics

    def _discover_swarm_stacks(self) -> Optional[List[ZabbixMetric]]:
        """
        Discover swarm stacks

        :return: the discovery metrics
        """
        info = self._docker_client.info()

        if (
            "Swarm" not in info or
            info["Swarm"] == "inactive" or
            "NodeID" not in info["Swarm"] or
            info["Swarm"]["NodeID"] == "" or
            "RemoteManagers" not in info["Swarm"] or
            info["Swarm"]["RemoteManagers"] is None
        ):
            self._logger.debug("node is not a swarm member")

            return None

        node_id = info["Swarm"]["NodeID"]
        manager = False

        for remote_manager in info["Swarm"]["RemoteManagers"]:
            if remote_manager["NodeID"] == node_id:
                manager = True

        if manager is False:
            self._logger.debug("node is not a swarm manager")

            return None

        node_info = self._docker_client.inspect_node(node_id)
        leader = False

        if (
            "Leader" in node_info["ManagerStatus"] and
            node_info["ManagerStatus"]["Leader"] is True and
            node_info["ManagerStatus"]["Reachability"] == "reachable"
        ):
            leader = True

        if leader is False:
            self._logger.debug("node is not the swarm leader")

            return None

        metrics = []
        discovery_stacks = []

        services = self._docker_client.services(filters={
            "label": "com.docker.stack.namespace"
        })

        stacks = set()

        for service in services:
            stack_name = service["Spec"]["Labels"]["com.docker.stack.namespace"]

            stacks.add(stack_name)

        for stack_name in stacks:
            discovery_stacks.append({
                "{#NAME}": stack_name,
            })

        metrics.append(
            ZabbixMetric(
                self._config.get("zabbix", "hostname_cluster"),
                "docker.discovery.swarm.stacks",
                json.dumps({"data": discovery_stacks})))

        return metrics


class DockerDiscoveryEventsPollerWorker(threading.Thread):
    """ This class implements a discovery by events worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient,
                 discovery_service: DockerDiscoveryService):
        """
        Initialize the instance

        :param config: the config parser
        :param docker_client: the docker client
        :param discovery_service: the discovery service
        """
        super(DockerDiscoveryEventsPollerWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._discovery_service = discovery_service

    def run(self):
        """
        Execute the thread
        """
        until = None

        while True:
            since = datetime.datetime.utcnow() if until is None else until
            until = datetime.datetime.utcnow() + datetime.timedelta(seconds=self._config.getint("discovery",
                                                                                                "poll_events_interval"))
            containers_start = 0

            self._logger.info("querying events")
            for event in self._docker_client.events(since, until,
                                                    filters={
                                                        "type": "container",
                                                        "event": "start"
                                                    },
                                                    decode=True):
                self._logger.debug("new docker event: %s" % event)

                if event["status"] == "start":
                    containers_start += 1

            if containers_start > 0:
                self._discovery_service.trigger()
