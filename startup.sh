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

# Update pip
print_status "Updating pip..."
pip install --upgrade pip

# Install dependencies
print_status "Installing dependencies..."
pip install -r requirements.txt

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

# Check if ports are available
check_port() {
    if lsof -i :$1 >/dev/null; then
        print_error "Port $1 is already in use!"
        exit 1
    fi
}

print_status "Checking if required ports are available..."
check_port 9200 # OpenSearch
check_port 5601 # OpenSearch Dashboards
check_port 5044 # Logstash

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