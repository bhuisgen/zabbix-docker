from __future__ import division

import argparse
import configparser
import logging
import signal
import socket
import sys
import threading

import docker
import pyzabbix
import xdg

from zabbixdocker.version import __version__

from zabbixdocker.services.containers import DockerContainersService, DockerContainersStatsService,\
    DockerContainersRemoteService, DockerContainersTopService
from zabbixdocker.services.discovery import DockerDiscoveryService
from zabbixdocker.services.events import DockerEventsService


class Application(object):
    """This class implements the application instance"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Create the application instance singleton"""

        if Application._instance is None:
            with Application._lock:
                if Application._instance is None:
                    Application._instance = super(Application, cls).__new__(cls)

        return Application._instance

    def __init__(self):
        """Initialize the application instance"""

        self._logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = threading.Event()
        self._config = None

    def run(self):
        """Start the application """

        parser = argparse.ArgumentParser(prog="zabbix-docker",
                                         description="Discover and send Docker metrics to a Zabbix server.")
        parser.add_argument("--file", help="configuration file to use", metavar="<FILE>")
        parser.add_argument("--rootfs", help="rootfs path to use for system metrics", metavar="<PATH>")
        parser.add_argument("--server", help="Zabbix server to send metrics", metavar="<HOST>")
        parser.add_argument("--hostname", help="Zabbix hostname of sended metrics", metavar="<HOST>")
        parser.add_argument("--verbose", action="store_true", help="enable verbose output")
        parser.add_argument("-v", "--version", action="version", version="zabbix-docker %s" % __version__)
        args = parser.parse_args()

        config_default = """\
        # zabbix-docker.conf

        [main]
        log = yes
        log_level = error
        rootfs = /
        containers = yes
        containers_stats = yes
        containers_top = no
        containers_remote = no
        events = yes

        [docker]
        base_url = unix:///var/run/docker.sock
        timeout = 5

        [zabbix]

        [discovery]
        startup = 15
        interval = 300
        poll_events = yes
        poll_events_interval = 15

        [containers]
        startup = 15
        interval = 60

        [containers_stats]
        startup = 30
        interval = 60
        workers = 10

        [containers_top]
        startup = 30
        interval = 60
        workers = 10

        [containers_remote]
        startup = 30
        interval = 60
        workers = 10
        path = /etc/zabbix/scripts/trapper
        delay = 1
        user = root
        trappers = yes
        trappers_timestamp = no

        [events]
        startup = 30
        interval = 60
        """

        self._config = configparser.ConfigParser()
        self._config.read_string(config_default)

        if "file" in args and args.file:
            self._config.read(args.file)
        else:
            self._config.read([
                "/etc/zabbix-docker/zabbix-docker.conf",
                "%s/zabbix-docker/zabbix-docker.conf" % xdg.XDG_CONFIG_HOME
            ])

        if "rootfs" in args and args.rootfs:
            self._config.set("main", "rootfs", args.rootfs)

        if "server" in args and args.server:
            self._config.set("zabbix", "server", args.server)

        if "hostname" in args and args.hostname:
            self._config.set("zabbix", "hostname", args.hostname)

        if self._config.getboolean("main", "log"):
            if self._config.get("main", "log_level") == "error":
                level = logging.ERROR
            elif self._config.get("main", "log_level") == "warning":
                level = logging.WARN
            elif self._config.get("main", "log_level") == "info":
                level = logging.INFO
            elif self._config.get("main", "log_level") == "debug":
                level = logging.DEBUG
            else:
                level = logging.NOTSET

            logging.basicConfig(level=level)
            if level == logging.DEBUG:
                logging.getLogger("docker").setLevel(logging.DEBUG)
                logging.getLogger("pyzabbix").setLevel(logging.DEBUG)
                logging.getLogger("requests").setLevel(logging.WARNING)
                logging.getLogger("urllib3").setLevel(logging.WARNING)

        self._logger.info("starting application")

        self._logger.debug("registering signal handlers")
        signal.signal(signal.SIGINT, self.exit_handler)
        signal.signal(signal.SIGTERM, self.exit_handler)

        self._logger.debug("creating docker client")
        docker_client = docker.APIClient(
            base_url=self._config.get("docker", "base_url"),
            timeout=self._config.getint("docker", "timeout")
        )

        self._logger.debug("creating zabbix sender client")

        if self._config.has_option("zabbix", "server"):
            serverport = self._config.get("zabbix", "server").split(":")
            if ':' not in serverport:
                server = serverport[0]
                port = 10051
            else:
                server = serverport[0]
                port = int(serverport[1])

            zabbix_sender = pyzabbix.ZabbixSender(zabbix_server=server, zabbix_port=port)
        else:
            zabbix_sender = pyzabbix.ZabbixSender(use_config=True)

        if not self._config.has_option("zabbix", "hostname"):
            self._config.set("zabbix", "hostname", socket.gethostname())

        self._logger.info("starting services")

        containers_discovery_service = DockerDiscoveryService(self._config, self._stop_event, docker_client,
                                                              zabbix_sender)
        containers_discovery_service.start()

        if self._config.getboolean("main", "containers"):
            containers_service = DockerContainersService(self._config, self._stop_event, docker_client, zabbix_sender)
            containers_service.start()

        if self._config.getboolean("main", "containers_stats"):
            containers_stats_service = DockerContainersStatsService(self._config, self._stop_event, docker_client,
                                                                    zabbix_sender)
            containers_stats_service.start()

        if self._config.getboolean("main", "containers_top"):
            containers_top_service = DockerContainersTopService(self._config, self._stop_event, docker_client,
                                                                zabbix_sender)
            containers_top_service.start()

        if self._config.getboolean("main", "containers_remote"):
            containers_remote_service = DockerContainersRemoteService(self._config, self._stop_event, docker_client,
                                                                      zabbix_sender)
            containers_remote_service.start()

        if self._config.getboolean("main", "events"):
            events_service = DockerEventsService(self._config, self._stop_event, docker_client, zabbix_sender,
                                                 containers_discovery_service)
            events_service.start()

        while not self._stop_event.isSet():
            self._logger.debug("waiting signal")
            signal.pause()
            self._logger.debug("signal received")

        self._logger.info("stopping application")

        sys.exit(0)

    def exit_handler(self, signum, frame):
        """Handle the request signal to exit the application"""

        self._logger.info("signal %d received, exiting" % signum)
        self._stop_event.set()


if __name__ == "__main__":
    app = Application()

    app.run()
