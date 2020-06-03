from __future__ import division

import argparse
import configparser
import logging
import signal
import socket
import ssl
import sys
import threading

import docker
import xdg

from zabbixdocker.lib.zabbix import ZabbixSender
from zabbixdocker.services.containers import DockerContainersService, DockerContainersStatsService, \
    DockerContainersRemoteService, DockerContainersTopService
from zabbixdocker.services.discovery import DockerDiscoveryService
from zabbixdocker.services.events import DockerEventsService
from zabbixdocker.services.images import DockerImagesService
from zabbixdocker.services.networks import DockerNetworksService
from zabbixdocker.services.swarm import DockerSwarmService, DockerSwarmServicesService, DockerSwarmStacksService
from zabbixdocker.services.volumes import DockerVolumesService
from zabbixdocker.version import __version__


class Application(object):
    """This class implements the application instance"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Create the instance singleton"""
        if Application._instance is None:
            with Application._lock:
                if Application._instance is None:
                    Application._instance = super(Application, cls).__new__(cls)
                    Application._instance._initialized = False

        return Application._instance

    def __init__(self):
        """Initialize the instance"""
        if self._initialized is False:
            self._logger = logging.getLogger(self.__class__.__name__)
            self._stop_event = threading.Event()
            self._config = None

            self._initialized = True

    def run(self):
        """Start the application """

        parser = argparse.ArgumentParser(prog="zabbix-docker",
                                         description="Zabbix standalone agent to monitor Docker hosts.")
        parser.add_argument("-f", "--file", help="configuration file to use", metavar="<FILE>")
        parser.add_argument("--hostname", help="hostname to use for sending zabbix metrics", metavar="<HOST>")
        parser.add_argument("--rootfs", help="rootfs path to use for system metrics", metavar="<PATH>")
        parser.add_argument("--server", help="Zabbix server to send metrics", metavar="<HOST>")
        parser.add_argument("--verbose", action="store_true", help="enable verbose output")
        parser.add_argument("--version", action="version", version="zabbix-docker %s" % __version__)
        args = parser.parse_args()

        config_default = """\
        # zabbix-docker.conf

        [main]
        log = yes
        log_level = error
        rootfs = /
        containers = yes
        containers_stats = no
        containers_top = no
        containers_remote = no
        events = yes
        images = yes
        networks = yes
        volumes = yes
        swarm = no
        swarm_services = yes
        swarm_stacks = no

        [docker]
        base_url = unix:///var/run/docker.sock
        tls = no
        version = auto
        timeout = 60

        [zabbix]
        timeout = 60

        [discovery]
        startup = 15
        interval = 900
        containers_labels =
        networks_labels =
        swarm_services_labels =
        swarm_stacks_labels =
        poll_events = yes
        poll_events_interval = 60

        [containers]
        startup = 30
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

        [images]
        startup = 30
        interval = 60

        [networks]
        startup = 30
        interval = 60

        [volumes]
        startup = 30
        interval = 60

        [swarm]
        startup = 30
        interval = 60

        [swarm_services]
        startup = 30
        interval = 60

        [swarm_stacks]
        startup = 30
        interval = 60
        """

        self._config = configparser.ConfigParser(inline_comment_prefixes="#")
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

        if self._config.getboolean("docker", "tls") is True:
            for option in ["tls_ca", "tls_cert", "tls_key"]:
                if self._config.has_option("docker", option) is False:
                    raise ValueError(f"Missing configuration value for option '{option}' in section 'docker'")

        if (
            self._config.getboolean("main", "swarm") is True and
            self._config.has_option("zabbix", "hostname_cluster") is False
        ):
            print("Missing configuration value for option 'hostname_cluster' in section 'zabbix'", file=sys.stderr)

            sys.exit(1)

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
        signal.signal(signal.SIGINT, self._exit_handler)
        signal.signal(signal.SIGTERM, self._exit_handler)

        self._logger.debug("creating docker client")
        docker_client = docker.APIClient(
            base_url=self._config.get("docker", "base_url"),
            version=self._config.get("docker", "version"),
            tls=docker.TLSConfig(
                ca_cert=self._config.get("docker", "tls_ca"),
                client_cert=(self._config.get("docker", "tls_cert"), self._config.get("docker", "tls_key")),
                ssl_version=ssl.PROTOCOL_TLS,
                verify=True,
                assert_hostname=False
            ) if self._config.getboolean("docker", "tls") is True else False,
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

            zabbix_sender = ZabbixSender(zabbix_server=server, zabbix_port=port,
                                         timeout=self._config.getint("zabbix", "timeout"))
        else:
            zabbix_sender = ZabbixSender(use_config=True,
                                         timeout=self._config.getint("zabbix", "timeout"))

        if not self._config.has_option("zabbix", "hostname"):
            self._config.set("zabbix", "hostname", socket.gethostname())

        self._logger.info("starting services")

        discovery_service = DockerDiscoveryService(self._config, self._stop_event, docker_client, zabbix_sender)
        discovery_service.start()

        if self._config.getboolean("main", "containers") is True:
            containers_service = DockerContainersService(self._config, self._stop_event, docker_client, zabbix_sender)
            containers_service.start()

            if self._config.getboolean("main", "containers_stats") is True:
                containers_stats_service = DockerContainersStatsService(self._config, self._stop_event, docker_client,
                                                                        zabbix_sender)
                containers_stats_service.start()

            if self._config.getboolean("main", "containers_top") is True:
                containers_top_service = DockerContainersTopService(self._config, self._stop_event, docker_client,
                                                                    zabbix_sender)
                containers_top_service.start()

            if self._config.getboolean("main", "containers_remote") is True:
                containers_remote_service = DockerContainersRemoteService(self._config, self._stop_event, docker_client,
                                                                          zabbix_sender)
                containers_remote_service.start()

        if self._config.getboolean("main", "events") is True:
            events_service = DockerEventsService(self._config, self._stop_event, docker_client, zabbix_sender,
                                                 discovery_service)
            events_service.start()

        if self._config.getboolean("main", "images") is True:
            images_service = DockerImagesService(self._config, self._stop_event, docker_client, zabbix_sender)
            images_service.start()

        if self._config.getboolean("main", "networks") is True:
            networks_service = DockerNetworksService(self._config, self._stop_event, docker_client, zabbix_sender)
            networks_service.start()

        if self._config.getboolean("main", "volumes") is True:
            volumes_service = DockerVolumesService(self._config, self._stop_event, docker_client, zabbix_sender)
            volumes_service.start()

        if self._config.getboolean("main", "swarm") is True:
            swarm_service = DockerSwarmService(self._config, self._stop_event, docker_client, zabbix_sender)
            swarm_service.start()

            if self._config.getboolean("main", "swarm_services") is True:
                swarm_services_service = DockerSwarmServicesService(self._config, self._stop_event, docker_client,
                                                                    zabbix_sender)
                swarm_services_service.start()

            if self._config.getboolean("main", "swarm_stacks") is True:
                swarm_stacks_service = DockerSwarmStacksService(self._config, self._stop_event, docker_client,
                                                                zabbix_sender)
                swarm_stacks_service.start()

        self._logger.debug("waiting signal")

        self._stop_event.wait()

        self._logger.debug("signal received")

        self._logger.info("stopping application")

        sys.exit(0)

    def _exit_handler(self, signum, frame):
        """Handle the request signal to exit the application"""

        self._logger.info("signal %d received, exiting" % signum)
        self._stop_event.set()


if __name__ == "__main__":
    app = Application()

    app.run()
