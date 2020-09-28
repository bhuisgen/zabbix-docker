# zabbix-docker

Docker monitoring agent for Zabbix

Boris HUISGEN <bhuisgen@hbis.fr>

## Introduction

Zabbix-docker is a standalone Zabbix agent to run on hosts to send Docker metrics to a Zabbix server or proxy. It
can send the metrics of Swarm clusters depending on the current leader node. All required Zabbix templates are provided
to simplify your Zabbix setup and to monitor quickly your Docker hosts.

Supports Docker Community Edition, Docker Entreprise Edition and Docker Universal Control Plane (UCP).

# Setup

## Zabbix server

Import the Zabbix templates provided in the directory *docs/zabbix/templates* and enable required discovery rules.

## Zabbix host

Download the docker image:

    $ docker pull bhuisgen/zabbix-docker:latest

Create and edit your configuration file:

    $ cp share/config/zabbix-docker.conf.dist zabbix-docker.conf
    $ vi zabbix-docker.conf

For more information on the configuration settings, read the following [documentation](doc/CONFIG.md)

The docker image can be used on any kind of docker host engine and OS.

### Standalone node

Create and run the container:

    $ docker run -it --name zabbix-docker \
        -v zabbix-docker.conf:/etc/zabbix-docker.conf \
        -v /var/run/docker.sock:/var/run/docker.sock \
        bhuisgen/zabbix-docker:latest

### Swarm node

Create a docker config resource:

    $ cat zabbix-docker.conf | docker config create zabbix-docker -

Create a global service to deploy agent on all cluster nodes:

    $ docker service create --mode global --name zabbix-docker \
        --config source=zabbix-docker,target=/etc/zabbix-docker.conf,mode=0644 \
        bhuisgen/zabbix-docker:latest

# Development

## Setup

Install the required python dependencies:

    $ python -m venv venv
    $ source venv/bin/activate
    $ (venv) pip install -r requirements.txt -r requirements.dev.txt

Create a configuration file and edit your zabbix hostname and the server settings:

    $ (venv) cp share/config/zabbix-docker.conf.dist zabbix-docker.conf
    $ (venv) vi zabbix-docker.conf

Everything is ready to run the agent:

    $ (venv) ./bin/zabbix-docker

## Test

Before submitting a contribution to this project, please run the unit tests:

    $ (venv) tox
