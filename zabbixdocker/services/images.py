from __future__ import division

import configparser
import logging
import queue
import threading

import docker

from pyzabbix import ZabbixMetric, ZabbixSender


class DockerImagesService(threading.Thread):
    """ This class implements the service which sends images metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerImagesService, self).__init__()
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
        worker = DockerImagesWorker(self._config, self._docker_client, self._zabbix_sender, self._queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("images", "startup") > 0:
            self._stop_event.wait(self._config.getint("images", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("images", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the metrics sending
        """
        self._logger.debug("requesting images metrics")
        self._queue.put("metrics")


class DockerImagesWorker(threading.Thread):
    """ This class implements a images worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 images_queue: queue.Queue):
        """
        Initialize the instance
        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param images_queue: the images queue
        """
        super(DockerImagesWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._images_queue = images_queue

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            item = self._images_queue.get()
            if item is None:
                break

            self._logger.info("sending images metrics")

            try:
                metrics = []

                images = self._docker_client.images(quiet=True)

                images_total = len(images)

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.images.total",
                        "%d" % images_total
                    )
                )

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send images metrics")
