#!/bin/bash

# Start the application in the background
docker compose -f docker-compose-ci.yml up -d

# Function to wait for an endpoint to return HTTP 200
wait_for_http_200() {
    local url=$1
    local name=$2
    local elapsed_time=0
    local timeout=300 # 5 minutes
    local auth=$3      # Optional basic auth credentials in 'user:password' format

    echo "Waiting for $name to start..."

    while true; do
        if [ $elapsed_time -eq $timeout ]; then
            echo "$name did not start within 5 minutes. Exiting."
            exit 1
        fi

        echo "Sending request to $url"
        if [ -n "$auth" ]; then
            response=$(curl -v -s -m 5 -u "$auth" "$url" 2>&1)
        else
            response=$(curl -v -s -m 5 "$url" 2>&1)
        fi

        echo "Response for $name:"
        if [ -z "$response" ]; then
            echo "No response received (connection failed or timed out)"
        else
            echo "$response"
        fi
        echo "------------------------"

        response_code=$(echo "$response" | grep -i "< HTTP" | awk '{print $3}')
        if [ -z "$response_code" ]; then
            echo "Response Code for $name: No HTTP status code received"
        else
            echo "Response Code for $name: $response_code"
        fi

        if [[ "$response_code" =~ ^[0-9]+$ ]] && [ "$response_code" -eq 200 ]; then
            echo "$name started successfully."
            break
        fi

        sleep 1
        elapsed_time=$((elapsed_time + 1))

        if [ $((elapsed_time % 60)) -eq 0 ]; then
            echo "Waiting for $name to start. Elapsed time: $elapsed_time seconds."
            echo "Docker containers:"
            docker ps
            echo "Network information:"
            docker network ls
            docker network inspect $(docker network ls -q)
        fi
    done
}

# URLs and their respective names using parallel indexed arrays
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
# Loop through the URLs and wait for each one
for i in "${!urls[@]}"; do
    if [ "${names[$i]}" == "Active MQ" ]; then
        wait_for_http_200 "${urls[$i]}" "${names[$i]}" "admin:admin"
    else
        wait_for_http_200 "${urls[$i]}" "${names[$i]}"
    fi
done
