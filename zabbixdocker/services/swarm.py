from __future__ import division

import configparser
import logging
import queue
import threading

import docker

from pyzabbix import ZabbixMetric, ZabbixSender


class DockerSwarmService(threading.Thread):
    """ This class implements the service which send docker swarm metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerSwarmService, self).__init__()
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
        worker = DockerSwarmWorker(self._config, self._docker_client, self._zabbix_sender, self._queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("swarm", "startup") > 0:
            self._stop_event.wait(self._config.getint("swarm", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("swarm", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the metrics sending
        """
        self._logger.debug("requesting swarm metrics")
        self._queue.put("metrics")


class DockerSwarmWorker(threading.Thread):
    """ This class implements a swarm worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 swarm_queue: queue.Queue):
        """
        Initialize the instance

        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param swarm_queue: the swarm queue
        """
        super(DockerSwarmWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._swarm_queue = swarm_queue

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            item = self._swarm_queue.get()
            if item is None:
                break

            self._logger.info("sending swarm metrics")

            try:
                if self._check_leader() is False:
                    self._logger.debug("node is not the swarm leader")

                    continue

                metrics = []

                nodes = self._docker_client.nodes()

                nodes_total = len(nodes)
                nodes_status_ready = 0
                nodes_status_down = 0
                nodes_available = 0
                nodes_unavailable = 0
                nodes_managers = 0
                nodes_workers = 0
                nodes_managers_reachable = 0
                nodes_managers_unreachable = 0

                for node in nodes:
                    if node["Status"]["State"] == "ready":
                        nodes_status_ready += 1
                    else:
                        nodes_status_down += 1

                    if node["Spec"]["Availability"] == "active":
                        nodes_available += 1
                    else:
                        nodes_unavailable += 1

                    if node["Spec"]["Role"] == "manager":
                        nodes_managers += 1

                        if node["ManagerStatus"]["Reachability"] == "reachable":
                            nodes_managers_reachable += 1
                        else:
                            nodes_managers_unreachable += 1
                    else:
                        nodes_workers += 1

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.total",
                        "%d" % nodes_total
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.status_ready",
                        "%d" % nodes_status_ready
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.status_down",
                        "%d" % nodes_status_down
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.available",
                        "%d" % nodes_available
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.unavailable",
                        "%d" % nodes_unavailable
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.managers",
                        "%d" % nodes_managers
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.workers",
                        "%d" % nodes_workers
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.managers_reachable",
                        "%d" % nodes_managers_reachable
                    )
                )
                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.nodes.managers_unreachable",
                        "%d" % nodes_managers_unreachable
                    )
                )

                configs = self._docker_client.configs()

                configs_total = len(configs)

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.configs",
                        "%d" % configs_total
                    )
                )

                secrets = self._docker_client.secrets()

                secrets_total = len(secrets)

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.secrets",
                        "%d" % secrets_total
                    )
                )

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send stacks metrics")

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


class DockerSwarmServicesService(threading.Thread):
    """ This class implements the service which send docker swarm services metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerSwarmServicesService, self).__init__()
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
        worker = DockerSwarmServicesWorker(self._config, self._docker_client, self._zabbix_sender, self._queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("swarm_services", "startup") > 0:
            self._stop_event.wait(self._config.getint("swarm_services", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("swarm_services", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the metrics sending
        """
        self._logger.debug("requesting services metrics")
        self._queue.put("metrics")


class DockerSwarmServicesWorker(threading.Thread):
    """ This class implements a swarm services worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 services_queue: queue.Queue):
        """
        Initialize the instance

        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param services_queue: the services queue
        """
        super(DockerSwarmServicesWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._services_queue = services_queue

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            item = self._services_queue.get()
            if item is None:
                break

            self._logger.info("sending services metrics")

            try:
                if self._check_leader() is False:
                    self._logger.debug("node is not the swarm leader")

                    continue

                metrics = []

                services = self._docker_client.services()

                services_total = len(services)

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.services.total",
                        "%d" % services_total
                    )
                )

                for service in services:
                    service_id = service["ID"]
                    service_name = service["Spec"]["Name"]
                    service_version = service["Version"]["Index"]
                    service_image = service["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"]

                    if "Global" in service["Spec"]["Mode"]:
                        service_mode = "global"
                    else:
                        service_mode = "replicated"

                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.version[%s]" % service_name,
                            "%d" % service_version
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.image[%s]" % service_name,
                            service_image
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.mode[%s]" % service_name,
                            service_mode
                        )
                    )

                    if service_mode == "replicated":
                        service_replicas = service["Spec"]["Mode"]["Replicated"]["Replicas"]

                        metrics.append(
                            ZabbixMetric(
                                self._config.get("zabbix", "hostname_cluster"),
                                "docker.swarm.services.replicas[%s]" % service_name,
                                "%d" % service_replicas
                            )
                        )

                    service_tasks = self._docker_client.tasks(filters={
                        "service": service_id,
                        "desired-state": ["running"]
                    })

                    service_tasks_total = len(service_tasks)
                    service_tasks_new = 0
                    service_tasks_pending = 0
                    service_tasks_assigned = 0
                    service_tasks_accepted = 0
                    service_tasks_preparing = 0
                    service_tasks_starting = 0
                    service_tasks_running = 0
                    service_tasks_complete = 0
                    service_tasks_failed = 0
                    service_tasks_shutdown = 0
                    service_tasks_rejected = 0
                    service_tasks_orphaned = 0
                    service_tasks_remove = 0

                    for service_task in service_tasks:
                        if service_task["Status"]["State"] == "new":
                            service_tasks_new += 1

                            continue

                        if service_task["Status"]["State"] == "pending":
                            service_tasks_pending += 1

                            continue

                        if service_task["Status"]["State"] == "assigned":
                            service_tasks_assigned += 1

                            continue

                        if service_task["Status"]["State"] == "accepted":
                            service_tasks_accepted += 1

                            continue

                        if service_task["Status"]["State"] == "preparing":
                            service_tasks_preparing += 1

                            continue

                        if service_task["Status"]["State"] == "starting":
                            service_tasks_starting += 1

                            continue

                        if service_task["Status"]["State"] == "running":
                            service_tasks_running += 1

                            continue

                        if service_task["Status"]["State"] == "complete":
                            service_tasks_complete += 1

                            continue

                        if service_task["Status"]["State"] == "failed":
                            service_tasks_failed += 1

                            continue

                        if service_task["Status"]["State"] == "shutdown":
                            service_tasks_shutdown += 1

                            continue

                        if service_task["Status"]["State"] == "rejected":
                            service_tasks_rejected += 1

                            continue

                        if service_task["Status"]["State"] == "orphaned":
                            service_tasks_orphaned += 1

                            continue

                        if service_task["Status"]["State"] == "remove":
                            service_tasks_remove += 1

                            continue

                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_total[%s]" % service_name,
                            "%d" % service_tasks_total
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_new[%s]" % service_name,
                            "%d" % service_tasks_new
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_pending[%s]" % service_name,
                            "%d" % service_tasks_pending
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_assigned[%s]" % service_name,
                            "%d" % service_tasks_assigned
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_accepted[%s]" % service_name,
                            "%d" % service_tasks_accepted
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_preparing[%s]" % service_name,
                            "%d" % service_tasks_preparing
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_starting[%s]" % service_name,
                            "%d" % service_tasks_starting
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_running[%s]" % service_name,
                            "%d" % service_tasks_running
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_complete[%s]" % service_name,
                            "%d" % service_tasks_complete
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_failed[%s]" % service_name,
                            "%d" % service_tasks_failed
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_shutdown[%s]" % service_name,
                            "%d" % service_tasks_shutdown
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_rejected[%s]" % service_name,
                            "%d" % service_tasks_rejected
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_orphaned[%s]" % service_name,
                            "%d" % service_tasks_orphaned
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.services.tasks_remove[%s]" % service_name,
                            "%d" % service_tasks_remove
                        )
                    )

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send services metrics")

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


class DockerSwarmStacksService(threading.Thread):
    """ This class implements the service which send docker swarm stacks metrics """

    def __init__(self, config: configparser.ConfigParser, stop_event: threading.Event, docker_client: docker.APIClient,
                 zabbix_sender: ZabbixSender):
        """
        Initialize the instance

        :param config: the configuration parser
        :param stop_event: the event to stop execution
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        """
        super(DockerSwarmStacksService, self).__init__()
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
        worker = DockerSwarmStacksWorker(self._config, self._docker_client, self._zabbix_sender, self._queue)
        worker.setDaemon(True)
        self._workers.append(worker)

        self._logger.info("service started")

        if self._config.getint("swarm_stacks", "startup") > 0:
            self._stop_event.wait(self._config.getint("swarm_stacks", "startup"))

        for worker in self._workers:
            worker.start()

        while True:
            self._execute()

            if self._stop_event.wait(self._config.getint("swarm_stacks", "interval")):
                break

        self._logger.info("service stopped")

    def _execute(self):
        """
        Execute the metrics sending
        """
        self._logger.debug("requesting stacks metrics")
        self._queue.put("metrics")


class DockerSwarmStacksWorker(threading.Thread):
    """ This class implements a swarm stacks worker thread """

    def __init__(self, config: configparser.ConfigParser, docker_client: docker.APIClient, zabbix_sender: ZabbixSender,
                 stacks_queue: queue.Queue):
        """
        Initialize the instance

        :param config: the configuration parser
        :param docker_client: the docker client
        :param zabbix_sender: the zabbix sender
        :param stacks_queue: the stacks queue
        """
        super(DockerSwarmStacksWorker, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._docker_client = docker_client
        self._zabbix_sender = zabbix_sender
        self._stacks_queue = stacks_queue

    def run(self):
        """
        Execute the thread
        """
        while True:
            self._logger.debug("waiting execution queue")
            item = self._stacks_queue.get()
            if item is None:
                break

            self._logger.info("sending stacks metrics")

            try:
                if self._check_leader() is False:
                    self._logger.debug("node is not the swarm leader")

                    continue

                metrics = []

                services = self._docker_client.services(filters={
                    "label": "com.docker.stack.namespace"
                })

                stacks = set()
                stacks_info = dict()

                for service in services:
                    stack_name = service["Spec"]["Labels"]["com.docker.stack.namespace"]

                    stacks.add(stack_name)

                stacks_total = len(stacks)

                metrics.append(
                    ZabbixMetric(
                        self._config.get("zabbix", "hostname_cluster"),
                        "docker.swarm.stacks.total",
                        "%d" % stacks_total
                    )
                )

                for stack_name in stacks:
                    stacks_info[stack_name] = {
                        "services_total": 0,
                        "services_healthy": 0,
                        "services_unhealthy": 0,
                        "services_error": 0
                    }

                for service in services:
                    service_id = service["ID"]

                    service_tasks = self._docker_client.tasks(filters={
                        "service": service_id,
                        "desired-state": ["running"]
                    })

                    service_tasks_total = len(service_tasks)
                    service_tasks_running = 0

                    for service_task in service_tasks:
                        if service_task["Status"]["State"] == "running":
                            service_tasks_running += 1

                    stacks_info[service["Spec"]["Labels"]["com.docker.stack.namespace"]]["services_total"] += 1

                    if service_tasks_running >= service_tasks_total:
                        stacks_info[service["Spec"]["Labels"]["com.docker.stack.namespace"]][
                            "services_healthy"] += 1
                    elif service_tasks_running > 0:
                        stacks_info[service["Spec"]["Labels"]["com.docker.stack.namespace"]][
                            "services_unhealthy"] += 1
                    else:
                        stacks_info[service["Spec"]["Labels"]["com.docker.stack.namespace"]][
                            "services_error"] += 1

                for stack_name in stacks:
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.stacks.services_total[%s]" % stack_name,
                            "%d" % stacks_info[stack_name]["services_total"]
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.stacks.services_healthy[%s]" % stack_name,
                            "%d" % stacks_info[stack_name]["services_healthy"]
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.stacks.services_unhealthy[%s]" % stack_name,
                            "%d" % stacks_info[stack_name]["services_unhealthy"]
                        )
                    )
                    metrics.append(
                        ZabbixMetric(
                            self._config.get("zabbix", "hostname_cluster"),
                            "docker.swarm.stacks.services_error[%s]" % stack_name,
                            "%d" % stacks_info[stack_name]["services_error"]
                        )
                    )

                if len(metrics) > 0:
                    self._logger.debug("sending %d metrics" % len(metrics))
                    self._zabbix_sender.send(metrics)
            except (IOError, OSError):
                self._logger.error("failed to send stacks metrics")

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
