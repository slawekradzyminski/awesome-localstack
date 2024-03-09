#!/bin/bash

docker network create --driver bridge my_network

# Start the application in the background
docker-compose up -d

# Initialize elapsed time
ELAPSED_TIME=0

# Wait for the application to start
while true; do
  # If the elapsed time reaches 1800 seconds (30 minutes), exit with error
  if [ $ELAPSED_TIME -eq 1800 ]; then
    echo "Application did not start within 30 minutes. Exiting."
    exit 1
  fi

  # Check if the application is up by making a request to the swagger UI
  RESPONSE_CODE=$(curl -s -o /dev/null -w "%{http_code}" 'http://localhost:4001/users/signup')

  if [ $RESPONSE_CODE -eq 200 ]; then
    break
  fi

  # Sleep for 1 second
  sleep 1

  # Increase the elapsed time
  ELAPSED_TIME=$((ELAPSED_TIME+1))

  # Print the elapsed time every 60 seconds
  if [ $((ELAPSED_TIME%60)) -eq 0 ]; then
    echo "Waiting for application to start. Elapsed time: $ELAPSED_TIME seconds."
  fi
done

echo "Application started successfully."

# Run smoke test for registration
RESPONSE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X 'POST' \
  'http://localhost:4001/users/signup' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "username": "user",
  "email": "user@example.com",
  "password": "pass",
  "roles": [
    "ROLE_ADMIN"
  ],
  "firstName": "John",
  "lastName": "Doe"
}')

if [ $RESPONSE_CODE -ne 201 ]; then
  echo "Registration smoke test failed. Response code: $RESPONSE_CODE. Exiting."
  exit 1
fi

echo "Registration smoke test passed successfully."