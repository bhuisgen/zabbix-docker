from __future__ import division

import configparser
import logging
import queue
import threading

import docker

from pyzabbix import ZabbixMetric, ZabbixSender


class DockerNetworksService(threading.Thread):
    """ This class implements the service which sends networks metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerNetworksService, self).__init__()
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
        worker = DockerNetworksWorker(self._config, self._docker_client, self._zabbix_sender, self._queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("networks", "startup") > 0:
            self._stop_event.wait(self._config.getint("networks", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("networks", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the metrics sending
        """
        self._logger.debug("requesting networks metrics")
        self._queue.put("metrics")


class DockerNetworksWorker(threading.Thread):
    """ This class implements a networks worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 networks_queue: queue.Queue):
        """
        Initialize the instance
        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param networks_queue: the networks queue
        """
        super(DockerNetworksWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._networks_queue = networks_queue

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            item = self._networks_queue.get()
            if item is None:
                break

            self._logger.info("sending networks metrics")

            try:
                metrics = []

                networks = self._docker_client.networks()

                networks_total = len(networks)

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.networks.total",
                        "%d" % networks_total
                    )
                )

                for network in networks:
                    network_id = network["Id"]
                    network_name = network["Name"]

                    inspect = self._docker_client.inspect_network(network_id)

                    network_containers = 0
                    network_peers = 0

                    if "Containers" in inspect and inspect["Containers"] is not None:
                        network_containers = len(inspect["Containers"])

                    if "Peers" in inspect and inspect["Peers"] is not None:
                        network_peers = len(inspect["Peers"])

                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.networks.containers[%s]" % network_name,
                            "%d" % network_containers
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname"),
                            "docker.networks.peers[%s]" % network_name,
                            "%d" % network_peers
                        )
                    )

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send networks metrics")
