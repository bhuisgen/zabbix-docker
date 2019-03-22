from __future__ import division

import datetime
import logging
import queue
import threading
import time

import pyzabbix


class DockerEventsService(threading.Thread):
    """This class implements the events service thread"""

    def __init__(self, config, stop_event, docker_client, zabbix_sender, discovery_service):
        """Initialize the thread"""

        super(DockerEventsService, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._workers = []
        self._events_queue = queue.Queue()
        self._config = config
        self._stop_event = stop_event
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._discovery_service = discovery_service

    def run(self):
        """Execute the thread"""

        worker = DockerEventsPollerWorker(self._config, self._docker_client, self._zabbix_sender, self._events_queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("events", "startup") > 0:
            self._stop_event.wait(self._config.getint("events", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self.execute()

            if self._stop_event.wait(self._config.getint("events", "interval")):
                break

        self._logger.info("service stopped")

    def execute(self):
        """Execute the service"""

        self._logger.debug("requesting service execution")
        self._events_queue.put("metrics")


class DockerEventsPollerWorker(threading.Thread):
    """This class implements a events poller worker thread"""

    def __init__(self, config, docker_client, zabbix_sender, events_queue):
        """Intialize the thread"""

        super(DockerEventsPollerWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._events_queue = events_queue

    def run(self):
        """Execute the thread"""

        until = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)

        while True:
            self._logger.debug("waiting execution queue")
            item = self._events_queue.get()
            if item is None:
                break

            self._logger.info("sending events metrics")

            try:
                since = until
                until = datetime.datetime.utcnow()

                events_container_create = 0
                events_container_start = 0
                events_container_die = 0
                events_container_oom = 0
                events_container_kill = 0
                events_container_stop = 0
                events_container_destroy = 0

                for event in self._docker_client.events(since,
                                                        until,
                                                        {"type": "container"},
                                                        True):
                    if event["status"] == "create":
                        events_container_create += 1

                    if event["status"] == "start":
                        events_container_start += 1

                    if event["status"] == "die":
                        events_container_die += 1

                    if event["status"] == "oom":
                        events_container_oom += 1

                    if event["status"] == "stop":
                        events_container_stop += 1

                    if event["status"] == "kill":
                        events_container_kill += 1

                    if event["status"] == "destroy":
                        events_container_destroy += 1

                metrics = []
                clock = int(time.time())

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.events[container,create]",
                        events_container_create,
                        clock))

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.events[container,start]",
                        events_container_start,
                        clock))

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.events[container,die]",
                        events_container_die,
                        clock))

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.events[container,oom]",
                        events_container_oom,
                        clock))

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.events[container,stop]",
                        events_container_stop,
                        clock))

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.events[container,kill]",
                        events_container_kill,
                        clock))

                metrics.append(
                    pyzabbix.ZabbixMetric(
                        self._config.get("zabbix", "hostname"),
                        "docker.events[container,destroy]",
                        events_container_destroy,
                        clock))

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send events metrics")

                pass

