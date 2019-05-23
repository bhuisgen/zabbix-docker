from __future__ import division

import configparser
import logging
import queue
import threading

import docker

from pyzabbix import ZabbixMetric, ZabbixSender


class DockerVolumesService(threading.Thread):
    """ This class implements the service which sends volumes metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerVolumesService, self).__init__()
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
        worker = DockerVolumesWorker(self._config, self._docker_client, self._zabbix_sender, self._queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("volumes", "startup") > 0:
            self._stop_event.wait(self._config.getint("volumes", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("volumes", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the metrics sending
        """
        self._logger.debug("requesting volumes metrics")
        self._queue.put("metrics")


class DockerVolumesWorker(threading.Thread):
    """ This class implements a volumes worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 volumes_queue: queue.Queue):
        """
        Initialize the instance
        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param volumes_queue: the volumes queue
        """
        super(DockerVolumesWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._volumes_queue = volumes_queue

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            item = self._volumes_queue.get()
            if item is None:
                break

            self._logger.info("sending volumes metrics")

            try:
                metrics = []

                volumes = self._docker_client.volumes()["Volumes"]

                volumes_total = len(volumes)

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.volumes.total",
                        "%d" % volumes_total
                    )
                )

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send volumes metrics")
