#!/bin/bash

docker network create my-private-ntwk 2>/dev/null || true

docker volume create influxdb-storage 2>/dev/null
docker volume create jenkins-data 2>/dev/null
docker volume create postgres-data 2>/dev/null
docker volume create ollama-data 2>/dev/null

echo "Starting PostgreSQL..."
docker run -d \
  --restart always \
  -p 5432:5432 \
  -e POSTGRES_DB=testdb \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -v postgres-data:/var/lib/postgresql/data \
  --name postgres \
  --network my-private-ntwk \
  postgres:16.1

echo "Starting ActiveMQ..."
docker run -d \
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

echo "Starting Backend..."
docker run -d \
  --restart always \
  -p 4001:4001 \
  --hostname backend \
  --add-host host.docker.internal:host-gateway \
  --network my-private-ntwk \
  --name backend \
  -e SPRING_PROFILES_ACTIVE=docker \
  -e SPRING_ARTEMIS_BROKER_URL=tcp://activemq:61616 \
  -e SPRING_DATASOURCE_URL=jdbc:postgresql://postgres:5432/testdb \
  -e SPRING_DATASOURCE_USERNAME=postgres \
  -e SPRING_DATASOURCE_PASSWORD=postgres \
  slawekradzyminski/backend:3.2.0

echo "Starting Frontend..."
docker run -d \
  --restart always \
  -p 8081:8081 \
  --network my-private-ntwk \
  --name frontend \
  slawekradzyminski/frontend:3.2.0

echo "Starting Prometheus..."
docker run -d \
  --restart always \
  -v "$(pwd)/prometheus/:/etc/prometheus/" \
  -p 9090:9090 \
  --network my-private-ntwk \
  --name prometheus \
  prom/prometheus:v3.1.0

echo "Starting InfluxDB..."
docker run -d \
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
  -e GF_SECURITY_ADMIN_PASSWORD=grafana \
  -v "$(pwd)/grafana/provisioning/:/etc/grafana/provisioning/" \
  --restart always \
  -p 3000:3000 \
  --network my-private-ntwk \
  --name grafana \
  grafana/grafana:11.5.1

echo "Starting Mailhog..."
docker run -d \
  --restart always \
  -p 8025:8025 \
  -p 1025:1025 \
  --hostname mailhog \
  --network my-private-ntwk \
  --name mailhog \
  mailhog/mailhog:v1.0.1

echo "Starting Consumer..."
docker run -d \
  --restart always \
  -p 4002:4002 \
  --hostname consumer \
  --add-host host.docker.internal:host-gateway \
  --network my-private-ntwk \
  --name consumer \
  slawekradzyminski/consumer:3.1.3

echo "Building Jenkins image..."
docker build -t custom-jenkins .

echo "Starting Jenkins..."
docker run -d \
  -p 8080:8080 \
  -p 50000:50000 \
  -v jenkins-data:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart always \
  --network my-private-ntwk \
  --name jenkins \
  custom-jenkins

echo "Starting Ollama..."
docker run -d \
  -p 11434:11434 \
  -v ollama-data:/root/.ollama \
  -e OLLAMA_MODELS_DIR=/root/.ollama \
  --restart unless-stopped \
  --network my-private-ntwk \
  --name ollama \
  slawekradzyminski/qwens@sha256:932f418cb484b0426b48c8e00788d3d84aa236be04b8e751224b784e41ec5802

echo "Starting Nginx Static (CDN)..."
docker run -d \
  --restart always \
  -p 8082:80 \
  -v "$(pwd)/images:/usr/share/nginx/html/images" \
  --hostname nginx \
  --network my-private-ntwk \
  --name nginx-static \
  nginx:1.29.1-perl

echo "All containers have been started!" 
