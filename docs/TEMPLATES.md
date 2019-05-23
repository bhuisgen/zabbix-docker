# Templates

## Docker Host

File: *template_docker_host.xml*

This template contains all basic host items like the default template *Template OS Linux* with discovery rules
for disks, filesystems and network interfaces.
 
Add this template to all your docker hosts.

## Docker Engine

File: *template_docker_engine.xml*

This template contains all docker items and discovery rules for containers, containers statistics (like CPU, memory,
top processes), images, networks and volumes

Add this template to all your docker hosts.

## Docker Swarm

File: *template_docker_swarm.xml*
 
This template contains all docker items and discovery rules for swarm resources like services, configs, secrets and
the cluster nodes.

Add it to all your swarm nodes. Zabbix-docker will detect itself which is the active manager leader of these nodes 
before sending any metrics to the same zabbix host. 

To use it, you should:

- configure the *hostname_cluster* option in *zabbix* section of zabbix-docker with the same value for all nodes of
your swarm cluster

- create a zabbix host without agent using the previously cluster hostname
 
- add this template to the cluster host 

## Docker Cluster

File: *template_docker_cluster.xml*
 
This template is a pure zabbix template containing all the aggregated items from the previous templates allowing you to
aggregate the metrics and resources of your docker nodes per cluster.

To use it, you should:

- create a zabbix host group with all the nodes of your cluster you want to aggregate metrics

- create a zabbix host without agent

- add the macro *{$DOCKER_CLUSTER.GROUP}* on this host with the name of the zabbix host group

- add this template to the host
