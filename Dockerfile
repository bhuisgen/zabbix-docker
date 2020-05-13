FROM alpine:3.10

ARG BUILD_DATE
ARG BUILD_VERSION
ARG GIT_COMMIT
ARG GIT_URL

LABEL maintainer="bhuisgen@hbis.fr" \
      org.label-schema.build-date="$BUILD_DATE" \
      org.label-schema.name="zabbix-docker" \
      org.label-schema.description="zabbix-docker image" \
      org.label-schema.vcs-ref="$GIT_COMMIT" \
      org.label-schema.vcs-url="$GIT_URL" \
      org.label-schema.vendor="Boris HUISGEN" \
      org.label-schema.version="$BUILD_VERSION" \
      org.label-schema.schema-version="1.0"

ENV ZABBIXDOCKER_VERSION=0.4.4

RUN apk add --update git python3 py3-pip && \
    git clone -b ${ZABBIXDOCKER_VERSION} https://github.com/bhuisgen/zabbix-docker.git /tmp/zabbix-docker && \
    cd /tmp/zabbix-docker && \
    python3 setup.py install && \
    rm -fr /tmp/zabbix-docker && \
    apk del git && \
    rm -f /root/*.apk && \
    rm -rf /var/cache/apk/*

ENTRYPOINT ["/entrypoint.sh"]
CMD []
