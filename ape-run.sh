#!/bin/bash

# Check if arguments are provided
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: ./ape-run.sh <test|clean|setup-registry> <network-type>"
    exit 1
fi

COMMAND=$1
NETWORK_TYPE=$2

# Run the appropriate command based on the provided argument
case $1 in
    test)
        ape test --network ethereum:mainnet-fork:hardhat tests_forked
        ;;
    clean-registry)
        ape run scripts/setup-metaregistry.py clean --network ethereum:"$NETWORK_TYPE"
        ;;
    setup-registry)
        ape run scripts/setup-metaregistry.py setup --network ethereum:"$NETWORK_TYPE"
        ;;
    *)
        echo "Invalid argument. Please use 'test' or 'deploy'"
        exit 1
        ;;
esac
