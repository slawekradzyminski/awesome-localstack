#!/bin/bash

docker network create --driver bridge my_network

# Start the application in the background
docker-compose up -d

# Function to wait for an endpoint to return HTTP 200
wait_for_http_200() {
  local url=$1
  local name=$2
  local elapsed_time=0
  local timeout=1800 # 30 minutes

  echo "Waiting for $name to start..."

  while true; do
    if [ $elapsed_time -eq $timeout ]; then
      echo "$name did not start within 30 minutes. Exiting."
      exit 1
    fi

    response_code=$(curl -s -o /dev/null -w "%{http_code}" "$url")

    if [ $response_code -eq 200 ]; then
      echo "$name started successfully."
      break
    fi

    sleep 1
    elapsed_time=$((elapsed_time+1))

    if [ $((elapsed_time%60)) -eq 0 ]; then
      echo "Waiting for $name to start. Elapsed time: $elapsed_time seconds."
    fi
  done
}

# URLs and their respective names
declare -A urls=(
  ["http://localhost:4001/swagger-ui.html"]="Backend"
  ["http://localhost:8081/login"]="Frontend"
  ["http://localhost:9090/"]="Prometheus"
  ["http://localhost:3000/login"]="Grafana"
  ["http://localhost:8161/"]="Active MQ"
  ["http://localhost:8025/"]="Mailhog"
  ["http://localhost:4002/actuator/prometheus"]="Email consumer"
)

# Loop through the URLs and wait for each one
for url in "${!urls[@]}"; do
  wait_for_http_200 "$url" "${urls[$url]}"
done
