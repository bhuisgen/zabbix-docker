from __future__ import division

import configparser
import logging
import os
import queue
import re
import threading
import time

import docker

from zabbixdocker.lib.zabbix import ZabbixMetric, ZabbixSender


class DockerContainersService(threading.Thread):
    """ This class implements the service which sends containers metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerContainersService, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._workers = []
        self._queue = queue.Queue()
        self._config = config
        self._stop_event = stop_event
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender

    def run(self):
        """
        Execute the thread
        """
        worker = DockerContainersWorker(self._config, self._docker_client, self._zabbix_sender, self._queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("containers", "startup") > 0:
            self._stop_event.wait(self._config.getint("containers", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("containers", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the metrics sending
        """
        self._logger.debug("requesting containers metrics")
        self._queue.put("metrics")


class DockerContainersWorker(threading.Thread):
    """ This class implements a containers worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 containers_queue: queue.Queue):
        """
        Initialize the instance
        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param containers_queue: the containers queue
        """
        super(DockerContainersWorker, self).__init__()
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

            self._logger.info("sending containers metrics")

            try:
                metrics = []

                containers = self._docker_client.containers(all=True)

                containers_total = len(containers)
                containers_running = 0
                containers_created = 0
                containers_stopped = 0
                containers_healthy = 0
                containers_unhealthy = 0

                for container in containers:
                    container_name = container["Names"][0][1:]

                    if container["Status"].startswith("Up"):
                        containers_running += 1

                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.status[%s]" % container_name,
                                "%d" % 1
                            )
                        )

                        if container["Status"].find("(healthy)") != -1:
                            containers_healthy += 1

                            metrics.append(
                                ZabbixMetric(
                                    self._config.get("zabbix", "hostname"),
                                    "docker.containers.health[%s]" % container_name,
                                    "%d" % 1
                                )
                            )
                        elif container["Status"].find("(unhealthy)") != -1:
                            containers_unhealthy += 1

                            metrics.append(
                                ZabbixMetric(
                                    self._config.get("zabbix", "hostname"),
                                    "docker.containers.health[%s]" % container_name,
                                    "%d" % 0
                                )
                            )
                    elif container["Status"] == "Created":
                        containers_created += 1

                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.status[%s]" % container_name,
                                "%d" % 0
                            )
                        )
                    else:
                        containers_stopped += 1

                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.status[%s]" % container_name,
                                "%d" % 0
                            )
                        )

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.total",
                        "%d" % containers_total
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.running",
                        "%d" % containers_running
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.created",
                        "%d" % containers_created
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stopped",
                        "%d" % containers_stopped
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.healthy",
                        "%d" % containers_healthy
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.unhealthy",
                        "%d" % containers_unhealthy
                    )
                )

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError, LookupError, ValueError):
                self._logger.error("failed to send containers metrics")


class DockerContainersStatsService(threading.Thread):
    """ The class implements the service which send containers statistics metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerContainersStatsService, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._queue = queue.Queue()
        self._workers = []
        self._config = config
        self._stop_event = stop_event
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._containers_stats = {}

    def run(self):
        """
        Execute the thread
        """
        for _ in (range(self._config.getint("containers_stats", "workers"))):
            worker = DockerContainersStatsWorker(self._config, self._docker_client, self._queue, self._containers_stats)
            worker.setDaemon(True)
            self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("containers_stats", "startup") > 0:
            self._stop_event.wait(self._config.getint("containers_stats", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("containers_stats", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the service
        """
        self._logger.info("sending available containers statistics metrics")

        try:
            metrics = []

            containers = self._docker_client.containers(all=True)

            for container_id in set(self._containers_stats) - set(map(lambda c: c["Id"], containers)):
                del self._containers_stats[container_id]

            containers_running = 0

            for container in containers:
                container_name = container["Names"][0][1:]

                if container["Status"].startswith("Up"):
                    self._queue.put(container)

                    containers_running += 1

                if container["Id"] not in self._containers_stats:
                    continue

                container_stats = self._containers_stats[container["Id"]]["data"]
                clock = self._containers_stats[container["Id"]]["clock"]

                cpu = \
                    (container_stats["cpu_stats"]["cpu_usage"]["total_usage"] -
                     container_stats["precpu_stats"]["cpu_usage"]["total_usage"]) / \
                    (container_stats["cpu_stats"]["system_cpu_usage"] -
                     container_stats["precpu_stats"]["system_cpu_usage"]) * 100
                cpu_system = \
                    (container_stats["cpu_stats"]["cpu_usage"]["usage_in_kernelmode"] -
                     container_stats["precpu_stats"]["cpu_usage"]["usage_in_kernelmode"]) / \
                    (container_stats["cpu_stats"]["system_cpu_usage"] -
                     container_stats["precpu_stats"]["system_cpu_usage"]) * 100
                cpu_user = \
                    (container_stats["cpu_stats"]["cpu_usage"]["usage_in_usermode"] -
                     container_stats["precpu_stats"]["cpu_usage"]["usage_in_usermode"]) / \
                    (container_stats["cpu_stats"]["system_cpu_usage"] -
                     container_stats["precpu_stats"]["system_cpu_usage"]) * 100
                cpu_periods = \
                    container_stats["cpu_stats"]["throttling_data"]["periods"] - \
                    container_stats["precpu_stats"]["throttling_data"]["periods"]
                cpu_throttled_periods = \
                    container_stats["cpu_stats"]["throttling_data"]["throttled_periods"] - \
                    container_stats["precpu_stats"]["throttling_data"]["throttled_periods"]
                cpu_throttled_time = \
                    container_stats["cpu_stats"]["throttling_data"]["throttled_time"] - \
                    container_stats["precpu_stats"]["throttling_data"]["throttled_time"]

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.cpu[%s]" % (
                            container_name),
                        "%.2f" % cpu,
                        clock))
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.cpu_system[%s]" % (
                            container_name),
                        "%.2f" % cpu_system,
                        clock))
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.cpu_user[%s]" % (
                            container_name),
                        "%.2f" % cpu_user,
                        clock))
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.cpu_periods[%s]" % (
                            container_name),
                        "%d" % cpu_periods,
                        clock))
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.cpu_throttled_periods[%s]" % (
                            container_name),
                        "%d" % cpu_throttled_periods,
                        clock))
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.cpu_throttled_time[%s]" % (
                            container_name),
                        "%d" % cpu_throttled_time,
                        clock))

                memory = \
                    container_stats["memory_stats"]["usage"] / container_stats["memory_stats"]["limit"] * 100

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.memory[%s]" % (
                            container_name),
                        "%.2f" % memory,
                        clock))

                proc = container_stats["pids_stats"]["current"]

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.containers.stats.proc[%s]" % (
                            container_name),
                        "%d" % proc,
                        clock))

                if (
                    "cpu_stats" in container_stats and
                    "cpu_usage" in container_stats["cpu_stats"] and
                    "percpu_usage" in container_stats["cpu_stats"]["cpu_usage"] and
                    isinstance(container_stats["cpu_stats"]["cpu_usage"]["percpu_usage"], int)
                ):
                    for i in range(len(container_stats["cpu_stats"]["cpu_usage"]["percpu_usage"])):
                        percpu = (container_stats["cpu_stats"]["cpu_usage"]["percpu_usage"][i] -
                                  container_stats["precpu_stats"]["cpu_usage"]["percpu_usage"][i]) / \
                                 (container_stats["cpu_stats"]["system_cpu_usage"] -
                                  container_stats["precpu_stats"]["system_cpu_usage"]) * 100

                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.percpu[%s,%d]" % (
                                    container_name, i),
                                "%.2f" % percpu,
                                clock))

                if (
                    "memory_stats" in container_stats and
                    "stats" in container_stats["memory_stats"]
                ):
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_active_anon[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["active_anon"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_active_file[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["active_file"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_cache[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["cache"]),
                            clock))
                    if "dirty" in container_stats["memory_stats"]["stats"]:
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_dirty[%s]" % (
                                    container_name),
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["dirty"]),
                                clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_hierarchical_memory_limit[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["hierarchical_memory_limit"]),
                            clock))
                    if "hierarchical_memsw_limit" in container_stats["memory_stats"]["stats"]:
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_hierarchical_memsw_limit[%s]" % (
                                    container_name),
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["hierarchical_memsw_limit"]),
                                clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_inactive_anon[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["inactive_anon"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_inactive_file[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["inactive_file"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_mapped_file[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["mapped_file"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_pgfault[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["pgfault"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_pgmajfault[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["pgmajfault"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_pgpgin[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["pgpgin"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_pgpgout[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["pgpgout"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_rss[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["rss"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_rss_huge[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["rss_huge"]),
                            clock))
                    if "swap" in container_stats["memory_stats"]["stats"]:
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_swap[%s]" % (
                                    container_name),
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["swap"]),
                                clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.stats_unevictable[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["stats"]["unevictable"]),
                            clock))
                    if "writeback" in container_stats["memory_stats"]["stats"]:
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_writeback[%s]" % (
                                    container_name),
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["writeback"]),
                                clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.max_usage[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["max_usage"]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.usage[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["usage"]),
                            clock))
                    if "failcnt" in container_stats["memory_stats"]:
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.failcnt[%s]" % (
                                    container_name),
                                "%d" % (
                                    container_stats["memory_stats"]["failcnt"]),
                                clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.stats.memory_stats.limit[%s]" % (
                                container_name),
                            "%d" % (
                                container_stats["memory_stats"]["limit"]),
                            clock))

                    if containers_running == 1:
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_active_anon",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_active_anon"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_active_file",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_active_file"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_cache",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_cache"]),
                                clock))
                        if "total_dirty" in container_stats["memory_stats"]["stats"]:
                            metrics.append(
                                ZabbixMetric(
                                    self._config.get("zabbix", "hostname"),
                                    "docker.containers.stats.memory_stats.stats_total_dirty",
                                    "%d" % (
                                        container_stats["memory_stats"]["stats"]["total_dirty"]),
                                    clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_inactive_anon",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_inactive_anon"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_inactive_file",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_inactive_file"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_mapped_file",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_mapped_file"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_pgfault",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_pgfault"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_pgmajfault",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_pgmajfault"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_pgpgout",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_pgpgout"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_pgpgin",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_pgpgin"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_rss",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_rss"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_rss_huge",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_rss_huge"]),
                                clock))
                        if "total_swap" in container_stats["memory_stats"]["stats"]:
                            metrics.append(
                                ZabbixMetric(
                                    self._config.get("zabbix", "hostname"),
                                    "docker.containers.stats.memory_stats.stats_total_swap",
                                    "%d" % (
                                        container_stats["memory_stats"]["stats"]["total_swap"]),
                                    clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.memory_stats.stats_total_unevictable",
                                "%d" % (
                                    container_stats["memory_stats"]["stats"]["total_unevictable"]),
                                clock))
                        if "total_writeback" in container_stats["memory_stats"]["stats"]:
                            metrics.append(
                                ZabbixMetric(
                                    self._config.get("zabbix", "hostname"),
                                    "docker.containers.stats.memory_stats.stats_total_writeback",
                                    "%d" % (
                                        container_stats["memory_stats"]["stats"]["total_writeback"]),
                                    clock))

                if 'networks' in container_stats:
                    for container_stats_network_ifname in list(container_stats["networks"].keys()):
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.rx_bytes[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["rx_bytes"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.rx_dropped[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["rx_dropped"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.rx_errors[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["rx_errors"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.rx_packets[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["rx_packets"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.tx_bytes[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["tx_bytes"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.tx_dropped[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["tx_dropped"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.tx_errors[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["tx_errors"]),
                                clock))
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.networks.tx_packets[%s,%s]" % (
                                    container_name,
                                    container_stats_network_ifname),
                                "%d" % (
                                    container_stats["networks"][container_stats_network_ifname]["tx_packets"]),
                                clock))

                if (
                    "blkio_stats" in container_stats and
                    "io_serviced_recursive" in container_stats["blkio_stats"] and
                    "io_service_bytes_recursive" in container_stats["blkio_stats"] and
                    isinstance(container_stats["blkio_stats"]["io_serviced_recursive"], int) and
                    isinstance(container_stats["blkio_stats"]["io_service_bytes_recursive"], int)
                ):
                    for i in range(len(container_stats["blkio_stats"]["io_serviced_recursive"])):
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.blkio_stats.io[%s,%d,%d,%s]" % (
                                    container_name,
                                    container_stats["blkio_stats"]["io_serviced_recursive"][i]["major"],
                                    container_stats["blkio_stats"]["io_serviced_recursive"][i]["minor"],
                                    container_stats["blkio_stats"]["io_serviced_recursive"][i]["op"]),
                                "%d" % (
                                    container_stats["blkio_stats"]["io_serviced_recursive"][i]["value"]),
                                clock))

                    for i in range(len(container_stats["blkio_stats"]["io_service_bytes_recursive"])):
                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname"),
                                "docker.containers.stats.blkio_stats.io_bytes[%s,%d,%d,%s]" % (
                                    container_name,
                                    container_stats["blkio_stats"]["io_service_bytes_recursive"][i]["major"],
                                    container_stats["blkio_stats"]["io_service_bytes_recursive"][i]["minor"],
                                    container_stats["blkio_stats"]["io_service_bytes_recursive"][i]["op"]),
                                "%d" % (
                                    container_stats["blkio_stats"]["io_service_bytes_recursive"][i]["value"]),
                                clock))

            if len(metrics) > 0:
                self._logger.debug("sending %d metrics" % len(metrics))
                self._zabbix_sender.send(metrics)
        except (IOError, OSError, LookupError, ValueError):
            self._logger.error("failed to send containers statistics metrics")


class DockerContainersStatsWorker(threading.Thread):
    """ This class implements a containers stats worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient,
                 containers_stats_queue: queue.Queue, containers_stats: dict):
        """
        Initialize the instance

        :param config: the configuration parser
        :param docker_client: the docker client
        :param containers_stats_queue: the container stats queue
        :param containers_stats: the container stats data
        """
        super(DockerContainersStatsWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._containers_stats_queue = containers_stats_queue
        self._containers_stats = containers_stats

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            container = self._containers_stats_queue.get()
            if container is None:
                break

            self._logger.info("querying statistics metrics for container %s" % container["Id"])

            try:
                data = self._docker_client.stats(container, decode=False, stream=False)

                self._containers_stats[container["Id"]] = {
                    "data": data,
                    "clock": int(time.time())
                }
            except (IOError, OSError, LookupError, ValueError):
                self._logger.error("failed to get statistics metrics for container %s" % container["Id"])


class DockerContainersTopService(threading.Thread):
    """ This class implements a service which sends containers top metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerContainersTopService, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._workers = []
        self._queue = queue.Queue()
        self._config = config
        self._stop_event = stop_event
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._containers_top = {}

    def run(self):
        """
        Execute the thread
        """
        for _ in (range(self._config.getint("containers_top", "workers"))):
            worker = DockerContainersTopWorker(self._config, self._docker_client, self._queue, self._containers_top)
            worker.setDaemon(True)
            self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("containers_top", "startup") > 0:
            self._stop_event.wait(self._config.getint("containers_top", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("containers_top", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the service
        """
        self._logger.info("sending available containers top metrics")

        try:
            metrics = []

            containers = self._docker_client.containers()

            for container_id in set(self._containers_top) - set(map(lambda c: c["Id"], containers)):
                del self._containers_top[container_id]

            for container in containers:
                container_name = container["Names"][0][1:]

                if container["Status"].startswith("Up"):
                    self._queue.put(container)

                if container["Id"] not in self._containers_top:
                    continue

                container_top = self._containers_top[container["Id"]]["data"]
                clock = self._containers_top[container["Id"]]["clock"]

                if not isinstance(container_top["Processes"], int):
                    continue

                for i in range(len(container_top["Processes"])):
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.top.cpu[%s,%s]" % (
                                container_name,
                                container_top["Processes"][i][1]),
                            "%s" % (container_top["Processes"][i][2]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.top.mem[%s,%s]" % (
                                container_name,
                                container_top["Processes"][i][1]),
                            "%s" % (container_top["Processes"][i][3]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.top.vsz[%s,%s]" % (
                                container_name,
                                container_top["Processes"][i][1]),
                            "%s" % (container_top["Processes"][i][4]),
                            clock))
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.containers.top.rss[%s,%s]" % (
                                container_name,
                                container_top["Processes"][i][1]),
                            "%s" % (container_top["Processes"][i][5]),
                            clock))

            if len(metrics) > 0:
                self._logger.debug("sending %d metrics" % len(metrics))
                self._zabbix_sender.send(metrics)
        except (IOError, OSError, LookupError, ValueError):
            self._logger.error("failed to send containers top metrics")


class DockerContainersTopWorker(threading.Thread):
    """ This class implements a containers top worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient,
                 containers_top_queue: queue.Queue, containers_top: dict):
        """
        Initialize the instance

        :param config: the configuration parser
        :param docker_client: the docker client
        :param containers_top_queue: the containers top queue
        :param containers_top: the containers top data
        """
        super(DockerContainersTopWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._containers_top_queue = containers_top_queue
        self._containers_top = containers_top

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            container = self._containers_top_queue.get()
            if container is None:
                break

            self._logger.info("querying top metrics for container %s" % container["Id"])

            try:
                data = self._docker_client.top(container, "aux")

                self._containers_top[container["Id"]] = {
                    "data": data,
                    "clock": int(time.time())
                }
            except (IOError, OSError, LookupError, ValueError):
                self._logger.error("failed to get top metrics for container %s" % container["Id"])


class DockerContainersRemoteService(threading.Thread):
    """ This class implements a service which execute remote commands to send custom containers metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerContainersRemoteService, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._workers = []
        self._queue = queue.Queue()
        self._config = config
        self._stop_event = stop_event
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._containers_outputs = {}
        self._counter = 0
        self._lock = threading.Lock()

    def run(self):
        """
        Execute the thread
        """
        for _ in (range(self._config.getint("containers_remote", "workers"))):
            worker = DockerContainersRemoteWorker(self._config, self._docker_client, self, self._queue,
                                                  self._containers_outputs)
            worker.setDaemon(True)
            self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("containers_remote", "startup") > 0:
            self._stop_event.wait(self._config.getint("containers_remote", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("containers_remote", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the service
        """
        with self._lock:
            if self._counter > self._config.getint("containers_remote", "interval"):
                self._counter = 0

            self._counter += 1

        self._logger.info("sending available containers trappers metrics")

        try:
            metrics = []

            containers = self._docker_client.containers()

            for container_id in set(self._containers_outputs) - set(map(lambda c: c["Id"], containers)):
                del self._containers_outputs[container_id]

            for container in containers:
                if container["Status"].startswith("Up"):
                    self._queue.put(container)

                if container["Id"] not in self._containers_outputs:
                    continue

                container_output = self._containers_outputs[container["Id"]]["data"]
                clock = self._containers_outputs[container["Id"]]["clock"]

                if self._config.getboolean("containers_remote", "trappers") is False:
                    continue

                for line in container_output.splitlines():
                    if self._config.getboolean("containers_remote", "trappers_timestamp"):
                        m = re.match(r'^([^\s]+) (([^\s\[]+)(?:\[([^\s]+)\])?) '
                                     r'(\d+) (?:"?((?:\\.|[^"])+)"?)$', line)
                        if m is None:
                            continue

                        hostname = self._config.get("zabbix", "hostname") if m.group(1) == "-" \
                            else m.group(1)
                        key = m.group(2)
                        timestamp = int(m.group(5)) if m.group(5) == int(m.group(5)) else clock
                        value = re.sub(r'\\(.)', "\\1", m.group(6))

                        metrics.append(ZabbixMetric(hostname, key, value, timestamp))
                    else:
                        m = re.match(r'^([^\s]+) (([^\s\[]+)(?:\[([^\s]+)\])?) '
                                     r'(?:"?((?:\\.|[^"])+)"?)$', line)
                        if m is None:
                            continue

                        hostname = self._config.get("zabbix", "hostname") if m.group(1) == "-" \
                            else m.group(1)
                        key = m.group(2)
                        timestamp = clock
                        value = re.sub(r'\\(.)', "\\1", m.group(5))

                        metrics.append(ZabbixMetric(hostname, key, value, timestamp))

            if len(metrics) > 0:
                self._logger.debug("sending %d metrics" % len(metrics))
                self._zabbix_sender.send(metrics)
        except (IOError, OSError, LookupError, ValueError):
            self._logger.error("failed to send containers trappers metrics")

            pass

    def counter(self):
        return self._counter


class DockerContainersRemoteWorker(threading.Thread):
    """ This class implements a containers remote worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient,
                 containers_remote_service: DockerContainersRemoteService, containers_remote_queue: queue.Queue,
                 containers_outputs: dict):
        """
        Initialize the instance

        :param config: the configuration parser
        :param docker_client: the docker client
        :param containers_remote_service: the containers remote service
        :param containers_remote_queue: the containers remote queue
        :param containers_outputs: the containers outputs data
        """
        super(DockerContainersRemoteWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._containers_remote_service = containers_remote_service
        self._containers_remote_queue = containers_remote_queue
        self._containers_outputs = containers_outputs

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            container = self._containers_remote_queue.get()
            if container is None:
                break

            self._logger.info("executing remote command(s) in container %s" % container["Id"])

            paths = self._config.get("containers_remote", "path").split(os.pathsep)
            delays = self._config.get("containers_remote", "delay").split(os.pathsep)

            for index, path in enumerate(paths):
                delay = min(int(delays[index]) if ((len(delays) > index) and (int(delays[index]) > 0)) else 1,
                            int(self._config.get("containers_remote", "interval")))

                if self._containers_remote_service.counter() % delay != 0:
                    self._logger.debug("command is delayed to next execution")
                    continue

                try:
                    execution = self._docker_client.exec_create(
                        container,
                        "/bin/sh -c \"stat %s >/dev/null 2>&1 && /usr/bin/find %s -type f -maxdepth 1 -perm /700"
                        " -exec {} \\; || /bin/true\"" % (path, path),
                        stderr=True,
                        tty=True, user=self._config.get("containers_remote", "user"))

                    data = self._docker_client.exec_start(execution["Id"])

                    inspect = self._docker_client.exec_inspect(execution["Id"])
                    if inspect["ExitCode"] == 0:
                        self._containers_outputs[container["Id"]] = {
                            "data": str(data, 'utf-8'),
                            "clock": int(time.time())
                        }
                except (IOError, OSError, LookupError, ValueError):
                    self._logger.error("failed to execute remote command in container %s" % container["Id"])
