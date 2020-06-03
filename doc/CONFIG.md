# Configuration

## Main

This section contains all the general options.

Most options enable or disable the monitoring of related Docker metrics. If these options are disabled the linked
configuration sections are not required.

Options:

* log
* log_level
* rootfs
* containers
* containers_stats
* containers_top
* containers_remote
* events
* images
* networks
* volumes
* swarm
* swarm_services
* swarm_stacks

**log**
* type: boolean
* values: yes, no
* default: yes

Enable the log messages during execution.

**log_level**
* type: string
* values: error, warning, info, debug
* default: error

Set the output level of log messages.

**rootfs**
* type: string
* values: path
* default: /

Set the rootfs path to use for gathering system metrics (ex: / to access to /proc, /sys). This is only required if the
agent is running with root privileges and inside a restricted container.

**containers**
* type: boolean
* values: yes, no
* default: yes

Enable the basic metrics of containers.

**containers_stats**
* type: boolean
* values: yes, no
* default: no

Enable the statistics metrics from containers ie CPUs, memory, swap and disks.

**containers** must be enabled for these metrics.

**containers_top**
* type: boolean
* values: yes, no
* default: no

Enable the top metrics from containers ie container internal processes. *containers* option must be enabled.

**containers** must be enabled for these metrics.

**containers_remote**
* type: boolean
* values: yes, no
* default: no

Enable the remote commands metrics ie user own metrics.

**containers** must be enabled for these metrics.

**events**
* type: boolean
* values: yes, no
* default: yes

Enable the metrics about events.

**images**
* type: boolean
* values: yes, no
* default: yes

Enable the metrics about images.

**networks**
* type: boolean
* values: yes, no
* default: yes

Enable the metrics about networks.

**volumes**
* type: boolean
* values: yes, no
* default: yes

Enable the metrics about volumes.

**swarm**
* type: boolean
* values: yes, no
* default: yes

Enable the metrics about swarm clusters.

The agent will send cluster metrics only if the local node is detected as the cluster swarm leader. Don't forget to set
the host name of your cluster (hostname_cluster) in the zabbix section.

**swarm_services**
* type: boolean
* values: yes, no
* default: yes

Enable the metrics about swarm services.

**swarm_stacks**
* type: boolean
* values: yes, no
* default: no

Enable the metrics about swarm stacks.

## Docker

This section contains all options related to the docker client configuration.

Default values should be sufficient for any kind of engine (local node or cluster node).

Options:
* base_url
* timeout

**base_url**
* type: string
* values: path, URL
* default: unix:///var/run/docker.sock

The path to the socket daemon or its URL if available from the network.

**timeout**
* type: integer
* default: 60

The timeout in seconds of all operations to the docker engine

## Zabbix

This section contains all options related to the zabbix configuration.

These options must be defined. Please note that no zabbix agent is required to push metrics to the zabbix server or
proxy.

Options:
* server
* hostname
* hostname_cluster
* timeout

**server**
* type: string
* default: value present in */etc/zabbix/zabbix_agentd.conf* if found

The address of zabbix server (format HOST:IP)

If no address is given, the default value will be extracted from the file */etc/zabbix/zabbix_agentd.conf*.

**hostname**
* type: string
* default: local hostname

The zabbix host to use for metrics from this node.

If no value is given, the default value will be the system hostname

**hostname_cluster**
* type: string
* default:

The zabbix host to use for cluster metrics from this node.

This value is required to send cluster metrics and must be the same on all cluster nodes

**timeout**
* type: integer
* default: 60

The timeout in seconds to send operations to zabbix

## Discovery

This section contains all options related to the discovery of resources and to send metrics to the server to create the
associated items.

Options:
* startup
* interval
* containers_labels
* networks_labels
* swarm_services_labels
* swarm_stacks_labels
* poll_events
* poll_events_interval

**startup**
* type: integer
* default: 15

The startup delay in seconds before discovering resources.

**interval**
* type: integer
* default: 15

The interval delay in seconds between discoveries.

**containers_labels**
* type: string
* default:

List of labels to filter discovered containers.

**networks_labels**
* type: string
* default:

List of labels to filter discovered networks.

**swarm_services_labels**
* type: string
* default:

List of labels to filter discovered swarm services.

**swarm_stacks_labels**
* type: string
* default:

List of labels to filter discovered swarm stacks.

**poll_events**
* type: boolean
* values: yes/no
* default: yes

Poll docker events to improve containers discovery.

**poll_events_interval**
* type: integer
* default: 60

Interval in seconds between events polling.

## Containers

This section contains all options related to the Docker containers metrics. It is mainly the containers state.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

## Containers stats

This section contains all options related to the Docker containers statistics metrics. It is mainly the CPU and memory
metrics of each container.

Options:
* startup
* interval
* workers

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

**workers**
* type: integer
* default: 10

The number of worker threads collecting metrics. Increase it depending of your workload.

## Containers top

This section contains all options related to the Docker containers "top" processes metrics. These metrics are useful to
monitor internal container processes like the top command.

Options:
* startup
* interval
* workers

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

**workers**
* type: integer
* default: 10

The number of worker threads collecting metrics. Increase it depending of your workload.

## Containers remote execution

This section contains all options related to Docker containers remote monitoring metrics.

The container remote monitoring allows to retrieve custom user metrics from Docker containers. zabbix-docker discovers
all containers and execute remote docker commands - like *docker exec* - to find any executable file (shell scripts or
binaries) in the list of allowed paths. For any files found they will be executed - still docker exec - and the console
outputs will be parsed to extract metrics - like the *zabbix-sender* - If the former part is docker-specific, the latter
is related only to zabbix and it allows to monitor application item. These scripts should be added directly in the
application image.

    [containers_remote]

* startup = 30                           *  startup time (seconds)
* interval = 60                          *  execution interval (seconds)
* workers = 10                           *  number of worker threads
* path = /etc/zabbix/scripts/trapper     *  paths of directories/files to execute remotely
                                            *
                                            *  path = /etc/zabbix/scripts/trapper:/script.sh:/usr/local/bin/foo
                                            *
                                            *  In case of a directory his execution is not recursive. The execution bit
                                            *  must be set on each file to be run.
                                            *
* delay = 1                              *  delay execution (step count)
                                            *
                                            *  With the following configuration:
                                            *
                                            *  interval=60
                                            *  path=/etc/zabbix/scripts/trapper:/etc/zabbix/discovery/trapper:/other
                                            *  delay=1:15
                                            *
                                            *  All executable files in /etc/zabbix/scripts/trapper will be run every
                                            *  60 s (60*1), every 15 m (60*15) for /etc/zabbix/discovery/trapper and
                                            *  and every 60 s (1 step) for /usr/local/bin/foo as the default delay
                                            *  is 1.
                                            *
* user = root                            *  remote user for executing files inside containers
* trappers = yes                         *  enable parsing of commands output for zabbix trapper metrics
* trappers_timestamp = no                *  parse lines with timestamps


## Docker events

This section contains all options related to Docker events metrics.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

## Images

This section contains all options related to Docker images metrics.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

## Networks

This section contains all options related to Docker network metrics.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

## Volumes

This section contains all options related to Docker volumes metrics.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

## Swarm

This section contains all options related to Docker Swarm cluster metrics.

The Swarm metrics will only be sent from the current leader. If a controller node is demoted, metrics will be sent from
the new promoted leader.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

## Swarm services

This section contains all options related to Docker Swarm services metrics.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.

## Swarm stacks

This section contains all options related to Docker Swarm stacks metrics.

These metrics are basically the sums of all services metrics in the same stack.

Options:
* startup
* interval

**startup**
* type: integer
* default: 30

The startup delay in seconds before sending metrics.

**interval**
* type: integer
* default: 60

The interval delay in seconds between sending.
