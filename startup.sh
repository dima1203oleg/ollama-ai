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

# Enhanced Docker check with multiple socket paths and diagnostics
print_status "Checking Docker status..."
docker_socket_paths=(
    "/var/run/docker.sock"
    "/Users/olegkizima/.docker/run/docker.sock"
    "/Users/olegkizima/Library/Containers/com.docker.docker/Data/docker.sock"
)

docker_running=false
for socket in "${docker_socket_paths[@]}"; do
    if [ -S "$socket" ]; then
        print_status "Found Docker socket at: $socket"
        if DOCKER_HOST="unix://$socket" docker info >/dev/null 2>&1; then
            docker_running=true
            export DOCKER_HOST="unix://$socket"
            break
        fi
    fi
done

if ! $docker_running; then
    print_error "Docker is not running or accessible!"
    echo -e "${YELLOW}Diagnostic information:${NC}"
    echo -e "1. Docker Desktop status:"
    pgrep -fl Docker || echo "Docker Desktop process not found"
    echo -e "\n2. Docker socket status:"
    for socket in "${docker_socket_paths[@]}"; do
        echo -n "$socket: "
        if [ -S "$socket" ]; then
            echo "exists"
            ls -l "$socket"
        else
            echo "not found"
        fi
    done
    echo -e "\n3. Docker client version:"
    docker version --format '{{.Client.Version}}' 2>/dev/null || echo "Cannot get Docker version"
    
    echo -e "\n${YELLOW}Please ensure Docker is running by following these steps:${NC}"
    echo -e "1. Open Docker Desktop application"
    echo -e "2. Wait for Docker engine to start completely"
    echo -e "3. Look for the green 'Running' status in Docker Desktop"
    echo -e "4. Try running: killall Docker && open -a Docker"
    echo -e "5. Run this script again once Docker is running"
    exit 1
fi

# Check if Python 3.11 is installed
if ! command -v python3.11 &> /dev/null; then
    print_error "Python 3.11 is not installed!"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    print_status "Creating virtual environment..."
    python3.11 -m venv venv
else
    print_warning "Virtual environment already exists, skipping creation"
fi

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" != *"venv"* ]]; then
    print_status "Activating virtual environment..."
    source venv/bin/activate
else
    print_warning "Virtual environment already activated"
fi

# Update pip and install base packages
print_status "Updating pip and installing base packages..."
pip install --no-cache-dir --upgrade pip setuptools wheel

# Install dependencies with improved reliability
print_status "Installing dependencies..."
pip install --no-cache-dir --upgrade pip setuptools wheel
pip install --no-cache-dir -r requirements.txt || {
    print_warning "First attempt failed, trying alternative installation method..."
    pip install --no-cache-dir --no-deps -r requirements.txt && \
    pip install --no-cache-dir -r requirements.txt
}

# Explicitly install potentially missing packages
print_status "Installing additional required packages..."
pip install --no-cache-dir urllib3 langchain-core

# Add a quick pause to ensure all installations complete
sleep 2

# Verify Python dependencies
print_status "Verifying Python dependencies..."
if python -c "import langchain, opensearchpy, pydantic, dotenv; print('All dependencies installed successfully!')"; then
    print_status "Dependencies verified successfully"
else
    print_error "Dependencies verification failed!"
    exit 1
fi

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    print_error "Docker is not running!"
    exit 1
fi

# Улучшенная функция проверки порта
check_port() {
    local port=$1
    if lsof -i :$port >/dev/null 2>&1; then
        print_error "Port $port is already in use!"
        print_warning "Attempting to identify process..."
        lsof -i :$port
        return 1
    fi
}

print_status "Checking if required ports are available..."
ports_ok=true
for port in 9200 5601 5044 9600; do  # Removed 11434
    if ! check_port $port; then
        ports_ok=false
    fi
done

if [ "$ports_ok" = false ]; then
    print_error "Some ports are in use. Please run ./unstartup.sh first"
    exit 1
fi

# Start containers
print_status "Starting Docker containers..."
docker-compose up -d

# Create data directory and customs_data.csv if they don't exist
print_status "Checking data directory and customs_data.csv..."
data_dir="./data"
customs_file="${data_dir}/customs_data.csv"

if [ ! -d "$data_dir" ]; then
    mkdir -p "$data_dir"
    print_status "Created data directory"
fi

if [ ! -f "$customs_file" ]; then
    # Create customs_data.csv with headers
    echo "date,product,quantity,value,country,customs,declaration_type,sender,receiver,receiver_code,declaration_number,trading_country,sending_country,delivery_terms,delivery_place,unit,weight_gross,weight_net,customs_weight,special_mark,contract,trademark,product_code,calculated_invoice_value_usd_kg,weight_unit,weight_diff,calculated_customs_value_net_usd_kg,calculated_customs_value_usd_add,calculated_customs_value_gross_usd_kg,min_base_usd_kg,min_base_diff,cz_net_usd_kg,cz_diff_usd_kg,preferential,full" > "$customs_file"
    print_status "Created empty customs_data.csv with headers"
fi

# Wait for services to be ready
print_status "Waiting for services to start (30 seconds)..."
sleep 30

# Run dependency check script
print_status "Running final dependency check..."
if [ -f "./scripts/check_dependencies.py" ]; then
    chmod +x ./scripts/check_dependencies.py
    ./scripts/check_dependencies.py
else
    print_error "check_dependencies.py script not found!"
    exit 1
fi

# Make all scripts in scripts directory executable
print_status "Making all scripts executable..."
if [ -d "./scripts" ]; then
    chmod +x ./scripts/*.py ./scripts/*.sh 2>/dev/null || true
    print_status "All scripts in ./scripts directory are now executable"
else
    print_warning "Scripts directory not found!"
fi

# Final status
print_status "Setup complete! Services should be available at:"
echo -e "${GREEN}OpenSearch:${NC} http://localhost:9200"
echo -e "${GREEN}OpenSearch Dashboards:${NC} http://localhost:5601"
echo -e "${GREEN}Logstash:${NC} http://localhost:5044"
echo -e "${GREEN}Ollama:${NC} http://localhost:11434"

# Check if query_customs.py exists and is executable
if [ -f "./scripts/query_customs.py" ]; then
    chmod +x ./scripts/query_customs.py
    print_status "You can now run queries using: ./scripts/query_customs.py"
fi