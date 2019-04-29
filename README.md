# zabbix-docker

Docker monitoring agent for Zabbix

Boris HUISGEN <bhuisgen@hbis.fr>

## Introduction

Zabbix-docker is an agent which monitors a docker engine, getting his metrics and sending them to a Zabbix server or
proxy. You can monitor a single docker engine, a pool of engines or a swarm cluster

## Setup

Install the required python dependencies:

    # python setup.py install

## Configuration

Add the required templates on your Zabbix server from the *docs/zabbix/templates* directory:

- *template_docker_host.xml*
- *template_docker_engine.xml*
- *template_docker_manager.xml*
- *template_docker_cluster.xml*

For more information on these templates, read the following [documentation](doc/TEMPLATES.md) 

Some global regular expressions must be created for the discovery rules:

| Name                                         | Expression type   | Expression        |
|----------------------------------------------|-------------------|-------------------|
| Docker mount points for discovery            | [Result is FALSE] | ^/etc             |
| Docker network interfaces for discovery      | [Result is FALSE] | ^veth             |
| Docker container names for discovery         | [Result is TRUE]  | .+                |
| Docker container process names for discovery | [Result is TRUE]  | .+                |

## Usage

Create the configuration file and configure it:

    # mkdir -p /etc/zabbix-docker
    # cp share/config/zabbix-docker.conf.dist /etc/zabbix-docker/zabbix-docker.conf
    # vim /etc/zabbix-docker/zabbix-docker.conf

For more information on the configuration settings, read the following [documentation](doc/CONFIG.md)

You can now run the agent:

    # ./bin/zabbix-docker
