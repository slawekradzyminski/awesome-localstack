#!/bin/sh
# Wait for Keycloak to be ready, then set mock user passwords via admin API.
# Keycloak's --import-realm creates users but plain-text passwords in JSON
# are not reliably hashed in all versions, so we reset them post-startup.

set -e

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8080}"
MAX_RETRIES=90
RETRY_INTERVAL=3

echo "Waiting for Keycloak at $KEYCLOAK_URL..."
for i in $(seq 1 $MAX_RETRIES); do
  if curl -sf -o /dev/null "$KEYCLOAK_URL/realms/master" 2>/dev/null; then
    echo "Keycloak is ready after $((i * RETRY_INTERVAL))s"
    break
  fi
  if [ "$i" -eq "$MAX_RETRIES" ]; then
    echo "ERROR: Keycloak not ready after $((MAX_RETRIES * RETRY_INTERVAL))s"
    exit 1
  fi
  sleep $RETRY_INTERVAL
done

# Get admin token
echo "Getting admin token..."
ADMIN_TOKEN=$(curl -sf -X POST \
  -d "grant_type=password&client_id=admin-cli&username=admin&password=admin" \
  "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" | \
  sed 's/.*"access_token":"\([^"]*\)".*/\1/')

if [ -z "$ADMIN_TOKEN" ]; then
  echo "ERROR: Failed to get admin token"
  exit 1
fi
echo "Got admin token"

set_user_password() {
  REALM=$1
  USERNAME=$2
  PASSWORD=$3

  echo "Setting password for $USERNAME in $REALM..."

  USER_ID=$(curl -sf \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$KEYCLOAK_URL/admin/realms/$REALM/users?username=$USERNAME" | \
    sed 's/.*"id":"\([^"]*\)".*/\1/')

  if [ -z "$USER_ID" ]; then
    echo "  ERROR: User $USERNAME not found in $REALM"
    return 1
  fi

  curl -sf -o /dev/null -X PUT \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"password\",\"value\":\"$PASSWORD\",\"temporary\":false}" \
    "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/reset-password"

  echo "  Password set for $USERNAME ($USER_ID)"
}

set_user_password "google-mock" "google-user" "GoogleUser123!"
set_user_password "github-mock" "github-user" "GitHubUser123!"

echo "Mock user initialization complete"
