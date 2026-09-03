#!/usr/bin/env bash
# ==============================================================================
# Elinor Commission System — One-Liner Automated Docker & SSL Installer
# ==============================================================================

set -e

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${GREEN}${BOLD}"
echo "=================================================================="
echo "    🚀 Elinor Commission System — Easy Docker & SSL Installer     "
echo "=================================================================="
echo -e "${NC}"

REPO_URL="https://github.com/yuzservice/elinor-commission.git"
TARGET_DIR="elinor-commission"

# 1. Setup & Navigate to Repository Directory
if [ ! -f "compose.yaml" ]; then
    echo -e "${BLUE}▶ [1/5] Setting up project directory...${NC}"
    if ! command -v git &> /dev/null; then
        echo -e "${YELLOW}Installing git and curl...${NC}"
        sudo apt-get update -y && sudo apt-get install -y git curl
    fi

    if [ ! -d "$TARGET_DIR" ]; then
        echo -e "Cloning repository from ${REPO_URL}..."
        git clone "$REPO_URL" "$TARGET_DIR"
        cd "$TARGET_DIR"
    else
        echo -e "Found existing '${TARGET_DIR}' folder, navigating and pulling latest changes..."
        cd "$TARGET_DIR"
        git pull --ff-only 2>/dev/null || true
    fi
else
    echo -e "${GREEN}✓ Already inside project directory.${NC}"
fi

# 2. Check / Install Docker & Docker Compose
echo -e "\n${BLUE}▶ [2/5] Checking Docker & Docker Compose...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker is not installed. Installing Docker and Compose plugin...${NC}"
    if [ -f /etc/debian_version ] || [ -f /etc/lsb-release ]; then
        sudo apt-get update -y
        sudo apt-get install -y ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update -y
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        sudo systemctl enable --now docker
        sudo usermod -aG docker "$USER" 2>/dev/null || true
        echo -e "${GREEN}✓ Docker installed successfully.${NC}"
    else
        echo -e "${RED}Error: Automatic docker install only supported on Debian/Ubuntu. Please install Docker manually.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Docker is already installed.${NC}"
fi

# Resolve Docker Compose command
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}Error: Docker Compose not found.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose ready.${NC}"

# 3. Domain & SSL Configuration
echo -e "\n${BLUE}▶ [3/5] Domain & Security (SSL / HTTPS) Configuration...${NC}"
HAS_SSL="n"
DOMAIN_NAME=""
SERVER_IP=""

echo -e "Do you want to configure a domain name with automatic free SSL (HTTPS)? (y/n) [Default: y]: "
read -r ssl_choice < /dev/tty || ssl_choice="y"
ssl_choice=${ssl_choice:-y}

if [[ "$ssl_choice" =~ ^[Yy]$ ]]; then
    HAS_SSL="y"
    while [ -z "$DOMAIN_NAME" ]; do
        echo -e "Enter your domain name (e.g. commission.example.com): "
        read -r DOMAIN_NAME < /dev/tty
        DOMAIN_NAME=$(echo "$DOMAIN_NAME" | tr -d ' ' | tr '[:upper:]' '[:lower:]')
    done
    echo -e "${GREEN}✓ Domain configured: https://${DOMAIN_NAME}${NC}"
else
    echo -e "Enter server IP address or hostname (Press Enter for localhost): "
    read -r SERVER_IP < /dev/tty || SERVER_IP="localhost"
    SERVER_IP=${SERVER_IP:-localhost}
    echo -e "${YELLOW}Running in HTTP mode without SSL on port 8010: http://${SERVER_IP}:8010${NC}"
fi

# Generate random secure passwords
SECRET_KEY=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 50 || echo "secret-key-$(date +%s)")
POSTGRES_PASSWORD=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 24 || echo "pgpass-$(date +%s)")

if [ -f .env ]; then
    cp .env .env.bak
fi

if [ "$HAS_SSL" = "y" ]; then
    cat <<EOF > .env
DEBUG=false
SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=${DOMAIN_NAME},localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://${DOMAIN_NAME}
APP_PORT=8010
DOMAIN_NAME=${DOMAIN_NAME}
POSTGRES_DB=elinor
POSTGRES_USER=elinor
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DATABASE_URL=postgresql://elinor:${POSTGRES_PASSWORD}@db:5432/elinor
SECURE_SSL_REDIRECT=true
SERVE_MEDIA=true
EOF
else
    cat <<EOF > .env
DEBUG=false
SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=${SERVER_IP},localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://${SERVER_IP}:8010,http://localhost:8010
APP_PORT=8010
POSTGRES_DB=elinor
POSTGRES_USER=elinor
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DATABASE_URL=postgresql://elinor:${POSTGRES_PASSWORD}@db:5432/elinor
SECURE_SSL_REDIRECT=false
SERVE_MEDIA=true
EOF
fi
echo -e "${GREEN}✓ Configuration saved to .env${NC}"

# 4. Build and Run Containers
echo -e "\n${BLUE}▶ [4/5] Building & Launching Docker Services...${NC}"
if [ "$HAS_SSL" = "y" ]; then
    echo -e "Starting Web, PostgreSQL, and Caddy (Automatic SSL Proxy)..."
    $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml up -d --build
else
    echo -e "Starting Web and PostgreSQL on port 8010..."
    $COMPOSE_CMD up -d --build
fi

echo -e "Waiting for database and auto-migrations to initialize..."
sleep 6

# 5. Superuser & Initial Data
echo -e "\n${BLUE}▶ [5/5] Initial Setup & Admin User...${NC}"
echo -e "Do you want to create an admin superuser now? (y/n) [Default: y]: "
read -r create_admin < /dev/tty || create_admin="y"
create_admin=${create_admin:-y}
if [[ "$create_admin" =~ ^[Yy]$ ]]; then
    $COMPOSE_CMD exec web python manage.py createsuperuser
fi

echo -e "Do you want to seed sample test data (lines, shifts, targets)? (y/n) [Default: n]: "
read -r seed_data < /dev/tty || seed_data="n"
if [[ "$seed_data" =~ ^[Yy]$ ]]; then
    $COMPOSE_CMD exec web python manage.py seed
fi

# Completion Banner
echo -e "\n${GREEN}${BOLD}=================================================================="
echo "    🎉 Elinor Commission System successfully installed!          "
echo -e "==================================================================${NC}"

if [ "$HAS_SSL" = "y" ]; then
    echo -e "🔗 Access URL: ${BOLD}https://${DOMAIN_NAME}${NC}"
    echo -e "🔒 SSL certificate is automatically managed & renewed by Caddy."
else
    echo -e "🔗 Access URL: ${BOLD}http://${SERVER_IP}:8010${NC}"
fi

echo -e "\nUseful commands:"
echo -e "  View logs:   ${YELLOW}$COMPOSE_CMD logs -f web${NC}"
echo -e "  Stop system: ${YELLOW}$COMPOSE_CMD down${NC}"
echo -e "  Restart:     ${YELLOW}$COMPOSE_CMD restart${NC}"
echo ""
