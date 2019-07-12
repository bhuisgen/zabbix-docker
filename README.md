# zabbix-docker

Docker monitoring agent for Zabbix

Boris HUISGEN <bhuisgen@hbis.fr>

## Introduction

Zabbix-docker is an agent which monitors a docker engine, getting his metrics and sending them directly to a Zabbix 
server or a Zabbix proxy. You can monitor a single docker engine or a swarm cluster.

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

| Name                                         | Expression type   | Expression                                | Note                              |
|----------------------------------------------|-------------------|-------------------------------------------|-----------------------------------|
| Docker mount points for discovery            | [Result is FALSE] | ^/etc                                     | Container mountpoints to ignore   |
| Docker network interfaces for discovery      | [Result is FALSE] | ^veth                                     | Host virtual interfaces to ignore |
| Docker container names for discovery         | [Result is FALSE] | ^(k8\|ucp-kube\|ucp-pause\|ucp-interlock) | Ignore useless CTs                |
| Docker container process names for discovery | [Result is TRUE]  | .+                                        |                                   |
| Docker network names for discovery           | [Result is TRUE]  | .+                                        |                                   |
| Docker swarm service names for discovery     | [Result is FALSE] | ^(ucp-.+-win\|ucp-.+-s390x)$              | Ignore useless services           |
| Docker swarm stack names for discovery       | [Result is TRUE]  | .+                                        |                                   |

## Usage

Create the configuration file and configure it:

    # mkdir -p /etc/zabbix-docker
    # cp share/config/zabbix-docker.conf.dist /etc/zabbix-docker/zabbix-docker.conf
    # vim /etc/zabbix-docker/zabbix-docker.conf

For more information on the configuration settings, read the following [documentation](doc/CONFIG.md)

You can now run the agent:

    # ./bin/zabbix-docker
