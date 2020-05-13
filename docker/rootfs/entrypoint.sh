#!/bin/sh

cd /usr/local/zabbix-docker || exit 1

exec bin/zabbix-docker -f zabbix-docker.conf $@
