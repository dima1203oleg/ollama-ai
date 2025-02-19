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

# Функция для принудительного освобождения порта
kill_port() {
    local port=$1
    if lsof -i :$port >/dev/null 2>&1; then
        print_warning "Found process on port $port:"
        lsof -i :$port
        print_warning "Attempting to kill process on port $port..."
        lsof -ti :$port | xargs kill -9
        if [ $? -eq 0 ]; then
            print_status "Successfully killed process on port $port"
            sleep 1  # Даем системе время на освобождение порта
            return 0
        else
            print_error "Failed to kill process on port $port"
            return 1
        fi
    fi
    return 0
}

# Проверка наличия Homebrew
if ! command -v brew >/dev/null 2>&1; then
    print_error "Homebrew не установлен. Установите Homebrew с https://brew.sh"
    exit 1
fi

# Проверка наличия coreutils
if ! command -v gtimeout >/dev/null 2>&1; then
    print_status "Установка coreutils..."
    brew install coreutils || {
        print_error "Не удалось установить coreutils"
        exit 1
    }
    print_status "coreutils успешно установлен"
fi

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

# Check for Python 3.11
print_status "Checking Python 3.11..."
if ! command -v python3.11 &> /dev/null; then
    print_error "Python 3.11 not found!"
    print_status "Installing Python 3.11..."
    brew install python@3.11 || {
        print_error "Failed to install Python 3.11"
        exit 1
    }
fi

# Verify Python version (macOS compatible version)
PYTHON_VERSION=$(python3.11 -V 2>&1 | awk '{print $2}')
if [[ ! "$PYTHON_VERSION" =~ ^3\.11\. ]]; then
    print_error "Failed to verify Python 3.11 version (found: $PYTHON_VERSION)"
    exit 1
else
    print_status "Found Python $PYTHON_VERSION"
fi

# Setup virtual environment
print_status "Setting up Python virtual environment..."
if [ -d "venv" ]; then
    print_warning "Found existing virtual environment"
    if [ "$VIRTUAL_ENV" != "" ]; then
        print_status "Deactivating current virtual environment..."
        deactivate
    fi
    print_status "Removing old virtual environment..."
    rm -rf venv
fi

print_status "Creating new virtual environment with Python 3.11..."
python3.11 -m venv venv || {
    print_error "Failed to create virtual environment"
    exit 1
}

print_status "Activating virtual environment..."
source venv/bin/activate || {
    print_error "Failed to activate virtual environment"
    exit 1
}

# Verify virtual environment
if [[ "$VIRTUAL_ENV" != *"venv"* ]]; then
    print_error "Virtual environment activation failed"
    exit 1
fi

if [[ $(python -V) != *"3.11"* ]]; then
    print_error "Wrong Python version in virtual environment"
    exit 1
fi

print_status "Virtual environment ready with Python $(python -V)"

# Install dependencies
print_status "Updating pip and installing dependencies..."
python -m pip install --upgrade pip setuptools wheel

# Install dependencies with improved reliability
print_status "Installing dependencies..."
pip install --no-cache-dir --upgrade pip setuptools wheel

# Install essential packages first
print_status "Installing essential packages..."
pip install --no-cache-dir pandas urllib3 langchain-core || {
    print_error "Failed to install essential packages"
    exit 1
}

# Install remaining dependencies
pip install --no-cache-dir -r requirements.txt || {
    print_warning "First attempt failed, trying alternative installation method..."
    pip install --no-cache-dir --no-deps -r requirements.txt && \
    pip install --no-cache-dir -r requirements.txt
}

# Create activation helper script
print_status "Creating venv activation helper..."
cat > ./scripts/activate_venv.sh << 'EOL'
#!/bin/bash
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Virtual environment not found!"
    exit 1
fi
EOL
chmod +x ./scripts/activate_venv.sh

# Add venv activation to .bashrc and .zshrc
print_status "Adding venv activation to shell configs..."
for rc in ".bashrc" ".zshrc"; do
    if [ -f "$HOME/$rc" ]; then
        if ! grep -q "source ./venv/bin/activate" "$HOME/$rc"; then
            echo "# Auto-activate venv for ollama-ai project" >> "$HOME/$rc"
            echo "if [ -d \"$PWD/venv\" ]; then source $PWD/venv/bin/activate; fi" >> "$HOME/$rc"
        fi
    fi
done

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

# Port checking and cleanup section
print_status "Checking if required ports are available..."
ports_ok=true
for port in 9200 5601 5044 9600; do
    if ! check_port $port; then
        print_warning "Attempting to free port $port..."
        if ! kill_port $port; then
            print_error "Could not free port $port"
            ports_ok=false
        fi
    fi
done

if [ "$ports_ok" = false ]; then
    print_error "Could not free all required ports. Please check running processes manually"
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

# Make sure venv is activated before running scripts
ensure_venv() {
    if [[ "$VIRTUAL_ENV" != *"venv"* ]]; then
        print_warning "Virtual environment not activated, activating now..."
        source venv/bin/activate || {
            print_error "Failed to activate virtual environment"
            exit 1
        }
    fi
}

# Before running any Python scripts
ensure_venv

# Run dependency check script with timeout and capture output
print_status "Running final dependency check..."
if [ -f "./scripts/check_dependencies.py" ]; then
    chmod +x ./scripts/check_dependencies.py
    
    # Activate virtual environment for the check if not already activated
    if [[ "$VIRTUAL_ENV" != *"venv"* ]]; then
        source venv/bin/activate
    fi
    
    # Run with increased timeout and ensure proper Python path
    PYTHONPATH="$(pwd)" gtimeout 60 python ./scripts/check_dependencies.py
    check_result=$?
    
    case $check_result in
        0)
            print_status "Dependency check completed successfully"
            ;;
        124)
            print_warning "Dependency check timed out (60s)"
            ;;
        *)
            print_warning "Dependency check failed with code $check_result"
            ;;
    esac
else
    print_warning "check_dependencies.py script not found!"
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

print_status "Important notes:"
echo -e "1. To activate the virtual environment manually, run: ${YELLOW}source venv/bin/activate${NC}"
echo -e "2. The environment will auto-activate in new terminal sessions"
echo -e "3. If you get 'command not found' errors, run: ${YELLOW}source venv/bin/activate${NC}"

# Check if query_customs.py exists and is executable
if [ -f "./scripts/query_customs.py" ]; then
    chmod +x ./scripts/query_customs.py
    print_status "You can now run queries using: ./scripts/query_customs.py"
fi