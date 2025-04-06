#!/bin/bash
# dns-updater-repair.sh - Fix and repair DNS Updater issues
# This script fixes common issues and ensures up-to-date code is used

# Colors for better readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log() { echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}SUCCESS: $1${NC}"; }
error() { echo -e "${RED}ERROR: $1${NC}"; }
warning() { echo -e "${YELLOW}WARNING: $1${NC}"; }

# Header
echo -e "${GREEN}=== DNS Updater Repair Tool ===${NC}"
echo "This script will diagnose and fix common DNS Updater issues"
echo

# Check if we're in the dns-updater directory
if [ ! -f "Dockerfile" ] || [ ! -f "requirements.txt" ]; then
    error "This script must be run from the dns-updater directory."
    echo "Please change to the dns-updater directory and try again."
    exit 1
fi

# Step 1: Check for necessary files
log "Checking for required files..."
REQUIRED_FILES=("api_client.py" "api_client_core.py" "api_client_requests.py" "api_client_alt.py" "dns_manager.py" "container_monitor.py" "logger.py" "main.py")
MISSING_FILES=()

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        MISSING_FILES+=("$file")
    fi
done

if [ ${#MISSING_FILES[@]} -gt 0 ]; then
    error "Missing required files: ${MISSING_FILES[*]}"
    echo "Please ensure all required files are present before continuing."
    exit 1
else
    success "All required files are present."
fi

# Step 2: Check for missing import issues
log "Checking for missing imports..."

# Check for 're' imports in api_client_alt.py
if ! grep -q "^import re" api_client_alt.py; then
    warning "api_client_alt.py is missing 're' import. Fixing..."
    sed -i '1,10s/^import os$/import os\nimport re/' api_client_alt.py
    success "Added missing 're' import to api_client_alt.py."
else
    success "api_client_alt.py has proper 're' import."
fi

# Check for 're' imports in api_client_requests.py
if ! grep -q "^import re" api_client_requests.py; then
    warning "api_client_requests.py is missing 're' import. Fixing..."
    sed -i '1,10s/^import os$/import os\nimport re/' api_client_requests.py
    success "Added missing 're' import to api_client_requests.py."
else
    success "api_client_requests.py has proper 're' import."
fi

# Check for APIConfig vs ConnectionConfig issues
if grep -q "APIConfig" api_client.py; then
    warning "api_client.py has references to 'APIConfig' instead of 'ConnectionConfig'. Fixing..."
    sed -i 's/APIConfig/ConnectionConfig/g' api_client.py
    success "Fixed APIConfig → ConnectionConfig in api_client.py."
else
    success "api_client.py is using correct ConnectionConfig class."
fi

# Step 3: Check for endpoint not found error handling in dns_manager.py
log "Checking for endpoint not found error handling..."
if ! grep -q "errorMessage.*Endpoint not found" dns_manager.py; then
    warning "dns_manager.py is missing endpoint not found error handling."
    echo -e "${YELLOW}Please manually add endpoint not found error handling in dns_manager.py${NC}"
    echo "Look for the remove_specific_dns method and add code to handle errorMessage = 'Endpoint not found'"
else
    success "dns_manager.py has endpoint not found error handling."
fi

# Step 4: Verify configuration variables
log "Checking configuration variables..."

# Create patch function for adding verification delay
add_verification_delay() {
    if ! grep -q "verification_delay" dns_manager.py; then
        warning "dns_manager.py is missing verification_delay configuration. Adding..."
        sed -i '/max_reconfigure_time/a \ \ \ \ \ \ \ \ # Verification check delay (set to 0 to disable the post-deletion delay)\n        self.verification_delay = int(os.environ.get('\''VERIFICATION_DELAY'\'', '\''0'\''))' dns_manager.py
        success "Added verification_delay configuration to dns_manager.py."
    else
        success "dns_manager.py already has verification_delay configuration."
    fi
}

# Attempt to add verification delay
add_verification_delay

# Step 5: Rebuild container
log "Would you like to rebuild the DNS Updater container now? (y/n)"
read -r rebuild
if [[ $rebuild =~ ^[Yy]$ ]]; then
    log "Rebuilding DNS Updater container..."
    docker build -t dns-updater:latest .
    
    log "Do you want to restart the container as well? (y/n)"
    read -r restart
    if [[ $restart =~ ^[Yy]$ ]]; then
        log "Stopping existing container..."
        docker stop dns-updater 2>/dev/null || true
        
        log "Removing existing container..."
        docker rm dns-updater 2>/dev/null || true
        
        log "Starting new container..."
        
        # Get current environment variables if possible
        ENV_VARS=""
        if docker inspect dns-updater &>/dev/null; then
            ENV_VARS=$(docker inspect dns-updater | grep -o '"OPNSENSE_URL=[^"]*"\|"LOG_LEVEL=[^"]*"\|"API_[^"]*"\|"DNS_[^"]*"\|"VERIFICATION_DELAY=[^"]*"' | sed 's/"//g' | sed 's/^/-e /')
            if [ -z "$ENV_VARS" ]; then
                warning "Could not extract environment variables. Using defaults."
                ENV_VARS="-e LOG_LEVEL=INFO -e VERIFICATION_DELAY=0"
            fi
        else
            warning "No existing container found. Using default environment variables."
            ENV_VARS="-e LOG_LEVEL=INFO -e VERIFICATION_DELAY=0"
        fi
        
        # Create command
        CMD="docker run -d --name dns-updater \
            -v /var/run/docker.sock:/var/run/docker.sock:rw \
            -v /etc/hostname:/etc/docker_host_name:ro \
            $ENV_VARS \
            dns-updater:latest"
        
        # Display the command
        echo "Running command:"
        echo "$CMD"
        
        # Execute the command
        eval "$CMD"
        
        success "Container restarted successfully."
    else
        success "Container rebuilt but not restarted."
    fi
else
    log "Skipping container rebuild."
fi

# Step 6: Provide additional recommendations
echo
log "Recommended environment variables for stable operation:"
echo "VERIFICATION_DELAY=0            # Disable post-delete delay for verification"
echo "LOG_LEVEL=INFO                  # Appropriate log level"
echo "DNS_SYNC_INTERVAL=60            # Sync interval in seconds"
echo "DNS_CLEANUP_INTERVAL=3600       # Cleanup interval in seconds"
echo "DNS_CACHE_TTL=300               # Cache TTL in seconds"

# Step 7: Run diagnostics
log "Would you like to run API diagnostics to verify the fixes? (y/n)"
read -r run_diagnostics
if [[ $run_diagnostics =~ ^[Yy]$ ]]; then
    log "Running API diagnostics..."
    python3 api_diagnostics.py
fi

# Final message
echo
success "DNS Updater repair completed."
echo "If the container is still having issues after restart, please check the logs using:"
echo "  docker logs dns-updater"
