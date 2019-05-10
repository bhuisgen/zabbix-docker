# Templates

## Docker Host

File: *template_docker_host.xml*

This template contains all basic host items like the default template *Template OS Linux* with discovery rules
for disks, filesystems and network interfaces.
 
Add it to all your docker hosts.

## Docker Engine

File: *template_docker_engine.xml*

This template contains all docker items and discovery rules for containers, containers statistics (like CPU
and memory) and containers top processes.

Add it to all your docker hosts.

## Docker Cluster

File: *template_docker_cluster.xml*
 
This template is a pure zabbix template containing all the aggregated items from the previous templates allowing you to
aggregate the metrics and resources of your docker nodes per cluster.

To use it, you should:

- create a zabbix host group with all the nodes of your cluster you want to aggregate metrics

- create a zabbix host without agent

- add the macro *{$DOCKER_CLUSTER.GROUP}* on this host with the name of the zabbix host group

- add it this template

## Docker Swarm

File: *template_docker_swarm.xml*
 
This template contains all docker items and discovery rules for swarm resources. 

Add it to all your swarm nodes. Zabbix-docker will detect itself which is the active manager leader of these nodes 
before sending any metrics to same zabbix host.

To use it, you should:

- configure the *hostname_cluster* option in *zabbix* section of zabbix-docker with the same value for all nodes

- create a zabbix host without agent using the previously cluster hostname
 
- add it this template 
