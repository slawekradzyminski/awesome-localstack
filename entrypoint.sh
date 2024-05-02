#!/bin/bash
# Adjust Docker socket permissions
sudo chmod 777 /var/run/docker.sock
# Execute the original Jenkins entrypoint
exec /usr/local/bin/jenkins.sh
