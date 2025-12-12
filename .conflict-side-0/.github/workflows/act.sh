#!/usr/bin/env sh

# Check if the user provided a YAML file as an argument
if [ -z "$1" ]; then
  echo "Usage: $0 <path-to-workflow-file.yaml>"
  exit 1
fi

WORKFLOW_FILE="$1"

# Run the act command with the provided workflow file
act -W "$WORKFLOW_FILE" \
  --container-architecture linux/amd64 \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest \
  --pull=false \
