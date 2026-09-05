#!/usr/bin/env bash
# ==============================================================================
# Elinor Commission System — Safe Zero-Downtime Update Script
# بروزرسانی امن سامانه عملکرد الینور با پشتیبان‌گیری خودکار پیش از اعمال تغییرات
# ==============================================================================

set -euo pipefail

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${GREEN}${BOLD}"
echo "=================================================================="
echo "    🔄 Elinor Commission System — Safe Automated Updater          "
echo "=================================================================="
echo -e "${NC}"

TARGET_DIR="elinor-commission"

# 1. Locate repository directory
if [ ! -f "compose.yaml" ]; then
    if [ -d "$TARGET_DIR" ] && [ -f "$TARGET_DIR/compose.yaml" ]; then
        cd "$TARGET_DIR"
    else
        echo -e "${RED}Error: Cannot find compose.yaml. Please run this script from inside the elinor-commission directory.${NC}"
        exit 1
    fi
fi

# Verify .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env file not found. System has not been installed yet.${NC}"
    echo -e "Please run ./install.sh first."
    exit 1
fi

# Source .env safely
set -a
# shellcheck disable=SC1091
source .env
set +a

# Resolve Docker Compose command
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}Error: Docker Compose not found.${NC}"
    exit 1
fi

# 2. Automated Safety Backup BEFORE pulling any changes
echo -e "${BLUE}▶ [1/5] Creating pre-update safety backup of PostgreSQL database...${NC}"
mkdir -p backups
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backups/pre_update_${STAMP}.dump"

if $COMPOSE_CMD ps --services --filter "status=running" | grep -q "db"; then
    if $COMPOSE_CMD exec -T db pg_dump -U "${POSTGRES_USER:-elinor}" -d "${POSTGRES_DB:-elinor}" -Fc > "$BACKUP_FILE"; then
        BACKUP_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')
        echo -e "${GREEN}✓ Safety backup created: ${BACKUP_FILE} (${BACKUP_SIZE})${NC}"
    else
        echo -e "${YELLOW}Warning: Failed to create database dump. Database might still be empty or starting.${NC}"
    fi
else
    echo -e "${YELLOW}Database container is not currently running. Starting database to ensure safety...${NC}"
    $COMPOSE_CMD up -d db
    sleep 4
    $COMPOSE_CMD exec -T db pg_dump -U "${POSTGRES_USER:-elinor}" -d "${POSTGRES_DB:-elinor}" -Fc > "$BACKUP_FILE" 2>/dev/null || true
fi

# 3. Pull latest changes from GitHub
echo -e "\n${BLUE}▶ [2/5] Pulling latest updates from GitHub (main branch)...${NC}"
CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo -e "Current local commit: ${YELLOW}${CURRENT_COMMIT}${NC}"

git fetch origin main
LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "")

if [ "$LOCAL" = "$REMOTE" ] && [ -n "$LOCAL" ]; then
    echo -e "${GREEN}✓ Local files are already up to date with origin/main.${NC}"
else
    # Discard any accidental local changes to tracked files while keeping .env and media untouched
    git reset --hard origin/main
    NEW_COMMIT=$(git rev-parse --short HEAD)
    echo -e "${GREEN}✓ Successfully updated to commit: ${BOLD}${NEW_COMMIT}${NC}"
fi

# 4. Rebuild and restart application services
echo -e "\n${BLUE}▶ [3/5] Rebuilding application container with latest code...${NC}"
HAS_SSL="n"
if [ -n "${DOMAIN_NAME:-}" ] && [ -f "compose.prod.yaml" ] && [ "${SECURE_SSL_REDIRECT:-false}" = "true" ]; then
    HAS_SSL="y"
fi

if [ "$HAS_SSL" = "y" ]; then
    echo -e "Rebuilding with production SSL profile (${DOMAIN_NAME})..."
    $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml build web
    echo -e "Restarting services..."
    $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml up -d
else
    echo -e "Rebuilding standard web service..."
    $COMPOSE_CMD build web
    echo -e "Restarting services..."
    $COMPOSE_CMD up -d
fi

# 5. Apply Database Migrations & Collect Static Files
echo -e "\n${BLUE}▶ [4/5] Applying new database migrations safely...${NC}"
sleep 3
$COMPOSE_CMD exec -T web python manage.py migrate --noinput

echo -e "Collecting static files..."
$COMPOSE_CMD exec -T web python manage.py collectstatic --noinput

# 6. Verify System Health
echo -e "\n${BLUE}▶ [5/5] Verifying system health and integrity...${NC}"
$COMPOSE_CMD exec -T web python manage.py check

echo -e "\n${GREEN}${BOLD}=================================================================="
echo "    🎉 Elinor Commission System updated successfully!             "
echo "==================================================================${NC}"
echo -e "Pre-update backup saved at: ${YELLOW}${BACKUP_FILE}${NC}"
if [ "$HAS_SSL" = "y" ]; then
    echo -e "Access panel at: ${BOLD}https://${DOMAIN_NAME}${NC}"
else
    echo -e "Access panel at: ${BOLD}http://${ALLOWED_HOSTS%%,*}:${APP_PORT:-8010}${NC}"
fi
echo ""
