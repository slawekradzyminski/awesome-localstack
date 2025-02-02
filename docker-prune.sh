#!/bin/bash

# This script will remove all unused Docker objects:
# - Containers
# - Networks
# - Images
# - Volumes
#
# Warning: This will remove all unused Docker resources. Be sure that you really want to do this.

read -p "WARNING: This will prune all unused Docker objects. Continue? (y/n): " response

if [[ "$response" != "y" ]]; then
  echo "Operation cancelled."
  exit 0
fi

# Prune Docker system resources.
# -a: Removes all unused images not just dangling ones.
# --volumes: Also removes all unused volumes.
docker system prune -a --volumes -f

echo "Docker resources pruned."
