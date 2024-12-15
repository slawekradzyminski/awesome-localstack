#!/bin/bash

echo "Starting containers..."
docker compose -f docker-compose-ci.yml up -d

wait_for_http_200() {
    local url=$1
    local name=$2
    local elapsed_time=0
    local timeout=300
    local auth=$3
    local last_log_time=0

    echo "Waiting for $name to start..."

    while true; do
        if [ $elapsed_time -eq $timeout ]; then
            echo "$name did not start within 5 minutes. Exiting."
            exit 1
        fi

        if [ -n "$auth" ]; then
            response=$(curl -s -m 5 -w "%{http_code}" -u "$auth" "$url" -o /dev/null 2>/dev/null)
        else
            response=$(curl -s -m 5 -w "%{http_code}" "$url" -o /dev/null 2>/dev/null)
        fi

        if [[ "$response" =~ ^[0-9]+$ ]] && [ "$response" -eq 200 ]; then
            echo "$name started successfully."
            break
        fi

        if [ $((elapsed_time - last_log_time)) -ge 30 ]; then
            echo "Still waiting for $name... (${elapsed_time}s elapsed, status: $response)"
            last_log_time=$elapsed_time
            
            echo "Current containers:"
            docker ps --format "table {{.Names}}\t{{.Status}}"
        fi

        sleep 1
        elapsed_time=$((elapsed_time + 1))
    done
}

urls=(
    "http://localhost:4001/swagger-ui.html"
    "http://localhost:8081/login"
    "http://localhost:8161/index.html"
    "http://localhost:8025/"
    "http://localhost:4002/actuator/prometheus"
)
names=(
    "Backend"
    "Frontend"
    "Active MQ"
    "Mailhog"
    "Email consumer"
)

for i in "${!urls[@]}"; do
    if [ "${names[$i]}" == "Active MQ" ]; then
        wait_for_http_200 "${urls[$i]}" "${names[$i]}" "admin:admin"
    else
        wait_for_http_200 "${urls[$i]}" "${names[$i]}"
    fi
done
