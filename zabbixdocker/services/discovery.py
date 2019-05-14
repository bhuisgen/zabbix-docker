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

                if self._config.getboolean("main", "networks") is True:
                    m = self._discover_networks()
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

            macros = dict()

            if "Labels" in container:
                if (
                    "com.docker.stack.namespace" in container["Labels"] and
                    "com.docker.stack.service.name" in container["Labels"]
                ):
                    macros["{#STACK}"] = container["Labels"]["com.docker.stack.namespace"]
                    macros["{#SERVICE}"] = container["Labels"]["com.docker.stack.service.name"]

                for label in str(self._config.get("discovery", "containers_labels")).split(","):
                    if label in container["Labels"]:
                        macros["{{#{}}}".format(label.upper())] = container["Labels"][label]

            discovery_containers.append({
                **{
                    "{#NAME}": container_name,
                }, **macros
            })

            if container["Status"].startswith("Up") is False:
                continue

            if self._config.getboolean("main", "containers_stats"):
                container_stats = self._docker_client.stats(container_id, decode=False, stream=False)

                discovery_containers_stats.append({
                    **{
                        "{#NAME}": container_name,
                    }, **macros
                })

                if (
                    "cpu_stats" in container_stats and
                    "cpu_usage" in container_stats["cpu_stats"] and
                    "percpu_usage" in container_stats["cpu_stats"]["cpu_usage"]
                ):
                    cpus = len(container_stats["cpu_stats"]["cpu_usage"]["percpu_usage"])

                    for i in range(cpus):
                        discovery_containers_stats_cpus.append({
                            **{
                                "{#NAME}": container_name,
                                "{#CPU}": "%d" % i,
                            }, **macros
                        })

                if "networks" in container_stats:
                    for container_stats_network_ifname in list(container_stats["networks"].keys()):
                        discovery_containers_stats_networks.append({
                            **{
                                "{#NAME}": container_name,
                                "{#IFNAME}": container_stats_network_ifname,
                            }, **macros
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
                                    **{
                                        "{#NAME}": container_name,
                                        "{#DEVMAJOR}": container_stats["blkio_stats"]["io_serviced_recursive"][j][
                                            "major"],
                                        "{#DEVMINOR}": container_stats["blkio_stats"]["io_serviced_recursive"][j][
                                            "minor"],
                                        "{#DEVNAME}": match.group(1)
                                    }, **macros
                                })

            if self._config.getboolean("main", "containers_top"):
                container_top = self._docker_client.top(container)
                if "Processes" in container_top:
                    for j in range(len(container_top["Processes"])):
                        discovery_containers_top.append({
                            **{
                                "{#NAME}": container_name,
                                "{#PID}": container_top["Processes"][j][1],
                                "{#CMD}": container_top["Processes"][j][7],
                            }, **macros
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

    def _discover_networks(self) -> Optional[List[ZabbixMetric]]:
        """
        Discover networks

        :return: the discovery metrics
        """
        metrics = []
        discovery_networks = []

        networks = self._docker_client.networks()

        for network in networks:
            network_name = network["Name"]

            macros = dict()

            if "Labels" in network:
                for label in str(self._config.get("discovery", "networks_labels")).split(","):
                    if label in network["Labels"]:
                        macros["{{#{}}}".format(label.upper())] = network["Labels"][label]

            discovery_networks.append({
                **{
                    "{#NAME}": network_name,
                }, **macros
            })

        metrics.append(
            ZabbixMetric(
                self._config.get("zabbix", "hostname"),
                "docker.discovery.networks",
                json.dumps({"data": discovery_networks})))

        return metrics

    def _discover_swarm_services(self) -> Optional[List[ZabbixMetric]]:
        """
        Discover swarm services

        :return: the discovery metrics
        """
        if self._check_leader() is False:
            self._logger.debug("node is not the swarm leader")

            return None

        metrics = []
        discovery_services = []

        services = self._docker_client.services()

        for service in services:
            service_name = service["Spec"]["Name"]

            macros = dict()

            if "com.docker.stack.namespace" in service["Spec"]["Labels"]:
                macros["{#STACK}"] = service["Spec"]["Labels"]["com.docker.stack.namespace"]

            for label in str(self._config.get("discovery", "swarm_services_labels")).split(","):
                if label in service["Spec"]["Labels"]:
                    macros["{{#{}}}".format(label.upper())] = service["Spec"]["Labels"][label]

            discovery_services.append({
                **{
                    "{#NAME}": service_name,
                }, **macros
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
        if self._check_leader() is False:
            self._logger.debug("node is not the swarm leader")

            return None

        metrics = []
        discovery_stacks = []

        services = self._docker_client.services(filters={
            "label": "com.docker.stack.namespace"
        })

        #
        # new
        #

        stacks = set()
        stacks_macros = dict()

        for service in services:
            stack_name = service["Spec"]["Labels"]["com.docker.stack.namespace"]

            stacks.add(stack_name)

            stacks_macros[stack_name] = dict()

            for label in str(self._config.get("discovery", "swarm_stacks_labels")).split(","):
                if label in service["Spec"]["Labels"]:
                    stacks_macros[stack_name]["{{#{}}}".format(label.upper())] = service["Spec"]["Labels"][label]

        for stack_name in stacks:
            discovery_stacks.append({
                **{
                    "{#NAME}": stack_name,
                }, **stacks_macros[stack_name]
            })

        metrics.append(
            ZabbixMetric(
                self._config.get("zabbix", "hostname_cluster"),
                "docker.discovery.swarm.stacks",
                json.dumps({"data": discovery_stacks})))

        return metrics

    def _check_leader(self) -> bool:
        """
        Check if the node is the current swarm leader

        :return: True if host is the leader; False otherwise
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
            return False

        node_id = info["Swarm"]["NodeID"]
        manager = False

        for remote_manager in info["Swarm"]["RemoteManagers"]:
            if remote_manager["NodeID"] == node_id:
                manager = True

        if manager is False:
            return False

        inspect = self._docker_client.inspect_node(node_id)
        leader = False

        if (
            "Leader" in inspect["ManagerStatus"] and
            inspect["ManagerStatus"]["Leader"] is True and
            inspect["ManagerStatus"]["Reachability"] == "reachable"
        ):
            leader = True

        if leader is False:
            return False


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
