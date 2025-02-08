#!/bin/bash

# Start the application in the background
docker compose -f docker-compose-jenkins.yml up -d

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

        response_code=$(curl -sL -o /dev/null -w "%{http_code}" "$url")

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
    "http://localhost:8080/login"
)
names=(
    "Jenkins"
)
# Loop through the URLs and wait for each one
for i in "${!urls[@]}"; do
        wait_for_http_200 "${urls[$i]}" "${names[$i]}"
done
