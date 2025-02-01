#!/bin/bash

docker network create my-private-ntwk 2>/dev/null || true

docker volume create influxdb-storage
docker volume create jenkins-data

echo "Starting Backend..."
docker run -d \
  --platform linux/amd64 \
  --restart always \
  -p 4001:4001 \
  --hostname backend \
  --add-host host.docker.internal:host-gateway \
  --network my-private-ntwk \
  --name backend \
  slawekradzyminski/backend:2.3

echo "Starting Frontend..."
docker run -d \
  --platform linux/amd64 \
  --restart always \
  -p 8081:8081 \
  --network my-private-ntwk \
  --name frontend \
  slawekradzyminski/frontend:2.0

echo "Starting Prometheus..."
docker run -d \
  --platform linux/amd64 \
  --restart always \
  -v "$(pwd)/prometheus/:/etc/prometheus/" \
  -p 9090:9090 \
  --network my-private-ntwk \
  --name prometheus \
  prom/prometheus:v2.50.1

echo "Starting InfluxDB..."
docker run -d \
  --platform linux/amd64 \
  -p 8086:8086 \
  -v influxdb-storage:/var/lib/influxdb \
  -e INFLUXDB_DB=db0 \
  -e INFLUXDB_ADMIN_USER=admin \
  -e INFLUXDB_ADMIN_PASSWORD=admin \
  --network my-private-ntwk \
  --name influxdb \
  influxdb:1.8

echo "Starting Grafana..."
docker run -d \
  --platform linux/amd64 \
  -e GF_SECURITY_ADMIN_PASSWORD=grafana \
  -v "$(pwd)/grafana/provisioning/:/etc/grafana/provisioning/" \
  --restart always \
  -p 3000:3000 \
  --network my-private-ntwk \
  --name grafana \
  grafana/grafana:10.3.4

echo "Starting ActiveMQ..."
docker run -d \
  --platform linux/amd64 \
  --restart always \
  -e ARTEMIS_USER=admin \
  -e ARTEMIS_PASSWORD=admin \
  -e ANONYMOUS_LOGIN="true" \
  -e EXTRA_ARGS="--http-host 0.0.0.0 --relax-jolokia --no-autotune" \
  -e DISABLE_SECURITY="true" \
  -e BROKER_CONFIG_GLOBAL_MAX_SIZE="512mb" \
  -p 61616:61616 \
  -p 8161:8161 \
  -p 5672:5672 \
  --hostname activemq \
  --network my-private-ntwk \
  --name activemq \
  apache/activemq-artemis:2.31.2

echo "Starting Mailhog..."
docker run -d \
  --platform linux/amd64 \
  --restart always \
  -p 8025:8025 \
  -p 1025:1025 \
  --hostname activemq \
  --network my-private-ntwk \
  --name mailhog \
  mailhog/mailhog:v1.0.1

echo "Starting Consumer..."
docker run -d \
  --platform linux/amd64 \
  --restart always \
  -p 4002:4002 \
  --hostname consumer \
  --add-host host.docker.internal:host-gateway \
  --network my-private-ntwk \
  --name consumer \
  slawekradzyminski/consumer:1.2

echo "Building Jenkins image..."
docker build -t custom-jenkins .

echo "Starting Jenkins..."
docker run -d \
  --platform linux/amd64 \
  -p 8080:8080 \
  -p 50000:50000 \
  -v jenkins-data:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart always \
  --network my-private-ntwk \
  --name jenkins \
  custom-jenkins

echo "All containers have been started!" 