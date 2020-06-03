# zabbix-docker

Docker monitoring agent for Zabbix

Boris HUISGEN <bhuisgen@hbis.fr>

## Introduction

Zabbix-docker is a standalone Zabbix agent to run on hosts to send Docker metrics to a Zabbix server or proxy. It
can send the metrics of Swarm clusters depending on the current leader node. All required Zabbix templates are provided
to simplify your Zabbix setup and to monitor quickly your Docker hosts.

Supports Docker Community Edition, Docker Entreprise Edition and Docker Universal Control Plane (UCP).

# Setup

Install the required python dependencies:

    $ python3 setup.py install

# Configuration

## Zabbix server

Import the Zabbix templates provided in the directory *docs/zabbix/templates* and enable required discovery rules.

## Zabbix host

Create the configuration file and configure it to set your zabbix hostname and the server settings:

    # mkdir -p /etc/zabbix-docker
    # cp share/config/zabbix-docker.conf.dist /etc/zabbix-docker/zabbix-docker.conf
    # vim /etc/zabbix-docker/zabbix-docker.conf

For more information on the configuration settings, read the following [documentation](doc/CONFIG.md)

Everything is ready to run the agent:

    # ./bin/zabbix-docker

# Docker setup

The docker image can be used on any docker engine.

### Standalone Engine

Pull the docker image:

    $ docker pull bhuisgen/zabbix-docker:0.4.4

Create and run the container:

    $ docker run -it --name zabbix-docker \
        -v /etc/zabbix-docker.conf:/etc/zabbix-docker.conf \
        -v /var/run/docker.sock:/var/run/docker.sock \
        bhuisgen/zabbix-docker:0.4.4

### Swarm Cluster

Pull the docker image:

    $ docker pull bhuisgen/zabbix-docker:latest

Create the docker configuration:

    $ cat /etc/zabbix-docker.conf | docker config create zabbix-docker -

Create a global service to deploy agent on all cluster nodes:

    $ docker service create --mode global --name zabbix-docker \
        --config source=zabbix-docker,target=/etc/zabbix-docker.conf,mode=0640 \
        bhuisgen/zabbix-docker:0.4.4
