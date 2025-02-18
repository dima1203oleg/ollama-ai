#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print status messages
print_status() {
    echo -e "${GREEN}[*] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[!] $1${NC}"
}

print_error() {
    echo -e "${RED}[x] $1${NC}"
}

# Confirm cleanup
read -p "This will remove all containers, virtual environment, and clean up the environment. Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    print_status "Cleanup cancelled"
    exit 1
fi

# Stop and remove Docker containers
print_status "Stopping and removing Docker containers..."
docker-compose down -v

# Remove Docker images
print_status "Removing related Docker images..."
docker images | grep -E 'opensearch|logstash' | awk '{print $3}' | xargs -r docker rmi -f

# Deactivate virtual environment if active
if [[ "$VIRTUAL_ENV" != "" ]]; then
    print_status "Deactivating virtual environment..."
    deactivate
fi

# Remove virtual environment
if [ -d "venv" ]; then
    print_status "Removing virtual environment..."
    rm -rf venv
fi

# Remove Python cache files
print_status "Removing Python cache files..."
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# Remove any log files
print_status "Removing log files..."
find . -type f -name "*.log" -delete 2>/dev/null

# Clean up port usage
print_status "Checking and cleaning up ports..."
for port in 9200 5601 5044 11434; do
    pid=$(lsof -ti :$port 2>/dev/null)
    if [ ! -z "$pid" ]; then
        print_warning "Killing process on port $port (PID: $pid)..."
        kill -9 $pid 2>/dev/null
    fi
done

print_status "Cleanup complete! All services and environments have been removed."
print_status "You may need to restart Docker if you experience any issues."