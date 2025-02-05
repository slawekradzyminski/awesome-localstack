#!/bin/bash

# This script stops all running Docker containers and then removes all unused Docker objects:
# - Containers
# - Networks
# - Images
# - Volumes
#
# Warning: This will stop running containers and remove unused Docker resources. Be sure that you really want to do this.

read -p "WARNING: This will stop all running containers and prune all unused Docker objects. Continue? (y/n): " response

if [[ "$response" != "y" ]]; then
  echo "Operation cancelled."
  exit 0
fi

# Stop all currently running containers, if any.
running_containers=$(docker ps -q)
if [[ -n "$running_containers" ]]; then
  echo "Stopping running containers..."
  docker stop $running_containers
else
  echo "No running containers to stop."
fi

# Prune Docker system resources.
# -a: Removes all unused images not just dangling ones.
# --volumes: Also removes all unused volumes.
echo "Pruning unused Docker resources..."
docker system prune -a --volumes -f

echo "Docker resources pruned."
