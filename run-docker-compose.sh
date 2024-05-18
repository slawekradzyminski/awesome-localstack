#!/bin/bash

# Start the application in the background
docker compose up -d

# Function to wait for an endpoint to return HTTP 200
wait_for_http_200() {
    local url=$1
    local name=$2
    local elapsed_time=0
    local timeout=1800 # 30 minutes
    local auth=$3      # Optional basic auth credentials in 'user:password' format

    echo "Waiting for $name to start..."

    while true; do
        if [ $elapsed_time -eq $timeout ]; then
            echo "$name did not start within 30 minutes. Exiting."
            exit 1
        fi

        if [ -n "$auth" ]; then
            response_code=$(curl -s -o /dev/null -w "%{http_code}" -u "$auth" "$url")
        else
            response_code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
        fi

        echo "Response Code for $name: $response_code" 

        if [ $response_code -eq 200 ]; then
            echo "$name started successfully."
            break
        fi

        sleep 1
        elapsed_time=$((elapsed_time + 1))

        if [ $((elapsed_time % 60)) -eq 0 ]; then
            echo "Waiting for $name to start. Elapsed time: $elapsed_time seconds."
        fi
    done
}

# URLs and their respective names using parallel indexed arrays
urls=(
    "http://localhost:4001/swagger-ui.html"
    "http://localhost:8081/login"
    "http://localhost:9090/graph"
    "http://localhost:3000/login"
    "http://localhost:8161/index.html"
    "http://localhost:8025/"
    "http://localhost:4002/actuator/prometheus"
    "http://localhost:8080/login"
)
names=(
    "Backend"
    "Frontend"
    "Prometheus"
    "Grafana"
    "Active MQ"
    "Mailhog"
    "Email consumer"
    "Jenkins"
)
# Loop through the URLs and wait for each one
for i in "${!urls[@]}"; do
    if [ "${names[$i]}" == "Active MQ" ]; then
        wait_for_http_200 "${urls[$i]}" "${names[$i]}" "admin:admin"
    else
        wait_for_http_200 "${urls[$i]}" "${names[$i]}"
    fi
done
