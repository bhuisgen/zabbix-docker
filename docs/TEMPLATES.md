# Templates

## Docker Host

File: *template_docker_host.xml*

This template contains all basic host items like the default template *Template OS Linux* with discovery rules
for disks, filesystems and network interfaces.
 
Add it to all your docker hosts.

## Docker Engine

File: *template_docker_engine.xml*

This template contains all docker engine items and discovery rules for containers, containers statistics (like CPU
and memory) and containers top processes.

Add it to all your docker hosts.

## Docker Manager

File: *template_docker_manager.xml*
 
This template contains all docker cluster items and discovery rules for services.

Add it all your swarm managers as zabbix-docker will detect himself which is the active leader before sending metrics.

To use it, you should do:

- configure the *hostname_cluster* option in *zabbix* section of zabbix-docker on all instances

- create a zabbix host without agent using the cluster hostname as configured previously
 
- add it this template 

## Docker Cluster

File: *template_docker_cluster.xml*
 
This template is a pure zabbix template containing all the aggregated items from the previous templates allowing you to
summarize the metrics and resources per cluster.

To use it, you should:

- create a zabbix host group with all the nodes of your cluster you want to aggregate metrics

- create a zabbix host without agent

- add the macro *{$DOCKER_CLUSTER.GROUP}* on this host with the name of the zabbix host group

- add it this template
