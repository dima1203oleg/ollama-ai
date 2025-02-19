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

# Check if required commands are available
check_requirements() {
    local requirements=(docker docker-compose lsof find)
    for cmd in "${requirements[@]}"; do
        if ! command -v $cmd >/dev/null 2>&1; then
            print_error "$cmd is required but not installed."
            exit 1
        fi
    done
}

# Function to deactivate all possible Python environments
deactivate_environments() {
    if [[ ! -z "$VIRTUAL_ENV" ]]; then
        print_status "Деактивирую виртуальное окружение: $VIRTUAL_ENV"
        deactivate 2>/dev/null && {
            print_status "Виртуальное окружение деактивировано"
            unset VIRTUAL_ENV
        } || print_warning "Не удалось деактивировать виртуальное окружение"
    else
        print_status "Активных виртуальных окружений не найдено"
    fi

    # Сброс переменных окружения Python
    unset PYTHONPATH
    unset PYTHONHOME
    print_status "Сброшены переменные окружения Python"
}

# Check requirements first
check_requirements

# Run environment deactivation
deactivate_environments

# Function to handle timeout for user input
get_confirmation() {
    local TIMEOUT=10
    local REPLY
    
    print_warning "У вас есть $TIMEOUT секунд для подтверждения (y/N)"
    read -t $TIMEOUT -p "Это действие удалит все контейнеры, виртуальное окружение и очистит среду. Продолжить? (y/N) " -n 1 -r REPLY
    echo
    
    if [ $? -gt 128 ]; then
        print_error "Время ожидания истекло. Отмена."
        exit 1
    fi
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_status "Очистка отменена"
        exit 1
    fi
}

# Function to run command with timeout
run_with_timeout() {
    local cmd="$1"
    local timeout="$2"
    local message="$3"
    
    print_status "$message"
    timeout $timeout bash -c "$cmd" || {
        print_warning "Команда не завершилась за $timeout секунд"
        return 1
    }
}

# Replace existing confirmation code with new function
get_confirmation

# Enhanced Docker container cleanup with timeout
cleanup_containers() {
    print_status "Attempting to stop containers gracefully..."
    timeout 30s docker-compose down || {
        print_warning "Graceful shutdown timed out after 30 seconds"
        print_status "Force stopping containers..."
        docker-compose kill
        docker-compose rm -f
    }
}

# Enhanced port cleanup with timeout
cleanup_port() {
    local port=$1
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        print_status "Checking port $port (attempt $attempt/$max_attempts)..."
        local pid=$(lsof -ti :$port 2>/dev/null)
        if [ -z "$pid" ]; then
            return 0
        fi
        
        print_warning "Found process on port $port (PID: $pid)"
        kill -15 $pid 2>/dev/null
        sleep 2
        
        if ! lsof -ti :$port >/dev/null 2>&1; then
            print_status "Successfully freed port $port"
            return 0
        fi
        
        if [ $attempt -eq $max_attempts ]; then
            print_status "Using force kill for port $port..."
            kill -9 $pid 2>/dev/null
            sleep 1
        fi
        
        ((attempt++))
    done
    
    if lsof -ti :$port >/dev/null 2>&1; then
        print_error "Failed to free port $port after $max_attempts attempts"
        return 1
    fi
}

print_status "Starting cleanup process..."

# Run each cleanup step with timeout
run_with_timeout "cleanup_containers" "30s" "Останавливаю контейнеры..." || true
run_with_timeout "docker images | grep -E 'opensearch|logstash|opensearch-dashboards' | awk '{print \$3}' | xargs -r docker rmi -f" "30s" "Удаляю Docker образы..." || true

# Deactivate virtual environment if active
print_status "Очистка окружения Python..."
deactivate_environments

# Remove virtual environment directory
if [ -d "venv" ]; then
    print_status "Удаляю директорию виртуального окружения..."
    rm -rf venv && print_status "Директория виртуального окружения удалена" || {
        print_error "Не удалось удалить директорию venv"
        exit 1
    }
else
    print_warning "Директория venv не найдена"
fi

# Remove local data directory
print_status "Removing local data directory..."
rm -rf "./data"

# Remove Python cache files
print_status "Removing Python cache files..."
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# Remove any log files
print_status "Removing log files..."
find . -type f -name "*.log" -delete 2>/dev/null

# Enhanced port cleanup
print_status "Cleaning up ports..."
for port in 9200 5601 5044 9600; do
    cleanup_port $port || print_warning "Could not fully clean port $port"
done

# Additional Docker container check
print_status "Checking for any remaining Docker containers..."
docker ps -a | grep -E 'opensearch|logstash|opensearch-dashboards' | awk '{print $1}' | xargs -r docker rm -f

# Cleanup Docker networks
print_status "Removing Docker networks..."
docker network ls | grep opensearch-net | awk '{print $1}' | xargs -r docker network rm

# Add final status check
print_status "Performing final status check..."
if pgrep -f "docker-compose" > /dev/null; then
    print_warning "Some docker-compose processes may still be running"
    pgrep -fl "docker-compose"
fi

if pgrep -f "opensearch\|logstash" > /dev/null; then
    print_warning "Some service processes may still be running"
    pgrep -fl "opensearch\|logstash"
fi

print_status "Очистка завершена!"
exit 0