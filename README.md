# zabbix-docker

Docker monitoring agent for Zabbix

Boris HUISGEN <bhuisgen@hbis.fr>

## Introduction

Zabbix-docker is a daemon to retrieve docker metrics from the running host where it runs and to send them to a Zabbix
server or proxy.

## Setup

Install the required python dependencies:

    # python setup.py install

## Configuration

Create the configuration file and configure it:

    # mkdir -p /etc/zabbix-docker
    # cp docs/zabbix-docker.conf.dist /etc/zabbix-docker/zabbix-docker.conf
    # vim /etc/zabbix-docker/zabbix-docker.conf


## Running

You can run the agent:

    # ./bin/zabbix-docker


### Zabbix server

#### Templates

You need to import all templates from *docs/zabbix/templates* directory:

- *template_docker_host.xml*: template for host metrics (like Template OS Linux)
- *template_docker_engine.xml*: template for docker metrics (with optinal discoveries)
- *template_docker_cluster.xml*: template for aggregated docker metrics by host groups

#### Regular expressions

Some global regular expressions must be created to customize metrics discoveries:

* Docker mount points for discovery

Expression: ^/etc [Result is FALSE]

This is necesseray to exclude all mounts binded by Docker.

* Docker network interfaces for discovery

Expression: ^veth [Result is FALSE]

This is necesseray to exclude all host network interfaces managed by Docker.

* Docker container names for discovery

Expression: .+ [Result is TRUE]

You can exclude some containers.

* Docker container process names for discovery

Expression: .+ [Result is TRUE]

You can exclude some container processes.


