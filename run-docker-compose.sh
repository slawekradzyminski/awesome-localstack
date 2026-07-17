#!/bin/bash

# Start the full profile explicitly. CI opts into a deterministic mock because
# hosted runners do not provide Docker Desktop Model Runner.
COMPOSE_FILES=(-f docker-compose.yml)
if [ "${USE_OLLAMA_MOCK:-false}" = "true" ]; then
    COMPOSE_FILES+=(-f docker-compose.model-mock.yml)
fi
docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans

if [ "${USE_OLLAMA_MOCK:-false}" = "true" ]; then
    MODEL_URL="http://localhost:11434/api/generate"
    MODEL_NAME="Ollama mock"
    MODEL_CHECK=(curl -fsS -H "Content-Type: application/json" -d '{"model":"qwen3.5:2b","prompt":"Provide a motivational quote","stream":false}' "$MODEL_URL")
else
    MODEL_URL="http://localhost:11434/api/tags"
    MODEL_NAME="Bonsai through the Docker Model Runner adapter"
    MODEL_CHECK=(docker compose "${COMPOSE_FILES[@]}" exec -T ollama-dmr-adapter python -c "import urllib.request; urllib.request.urlopen('$MODEL_URL', timeout=5).read()")
fi

echo "Waiting for $MODEL_NAME to start..."
for attempt in {1..120}; do
    if "${MODEL_CHECK[@]}" >/dev/null 2>&1; then
        echo "$MODEL_NAME started successfully."
        break
    fi
    if [ "$attempt" -eq 120 ]; then
        echo "$MODEL_NAME did not start within 2 minutes. Exiting."
        exit 1
    fi
    sleep 1
done

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
    "http://localhost:8081/swagger-ui/index.html"
    "http://localhost:8081/login"
    "http://localhost:9090/graph"
    "http://localhost:3000/login"
    "http://localhost:8161"
    "http://localhost:8025/"
    "http://localhost:4002/actuator/prometheus"
    "http://localhost:8082/realms/awesome-testing/.well-known/openid-configuration"
    "http://localhost:8081/images/applewatch.png"
)
names=(
    "Backend"
    "Frontend"
    "Prometheus"
    "Grafana"
    "Active MQ"
    "Mailpit"
    "Email consumer"
    "Keycloak"
    "Gateway-served product image"
)
# Loop through the URLs and wait for each one
for i in "${!urls[@]}"; do
        wait_for_http_200 "${urls[$i]}" "${names[$i]}"
done
