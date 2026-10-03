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

update_env_var() {
    local key="$1"
    local value="$2"
    local tmp
    tmp=$(mktemp)
    awk -v k="$key" -v v="$value" '
        BEGIN { FS = "=" }
        $1 == k { print k "=" v; found = 1; next }
        { print }
        END { if (!found) print k "=" v }
    ' .env > "$tmp"
    mv "$tmp" .env
}

normalize_domain() {
    local raw="$1"
    raw=$(printf '%s' "$raw" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
    raw=${raw#https://}
    raw=${raw#http://}
    raw=${raw%%/*}
    raw=${raw%%:*}
    printf '%s' "$raw"
}

valid_domain() {
    [[ "$1" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]]
}

reload_env() {
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
}

compose_up() {
    local recreate="${1:-}"
    if [ "${HAS_SSL}" = "y" ]; then
        # shellcheck disable=SC2086
        $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml up -d --remove-orphans $recreate
    else
        # shellcheck disable=SC2086
        $COMPOSE_CMD up -d --remove-orphans $recreate
    fi
}

certificate_matches_domain() {
    local domain="$1"
    local details
    if ! command -v openssl >/dev/null 2>&1; then
        return 1
    fi
    details=$(echo | openssl s_client -connect "127.0.0.1:443" -servername "$domain" 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName 2>/dev/null || true)
    printf '%s\n' "$details" | grep -F "DNS:${domain}" >/dev/null || printf '%s\n' "$details" | grep -F "CN = ${domain}" >/dev/null || printf '%s\n' "$details" | grep -F "CN=${domain}" >/dev/null
}

wait_for_certificate() {
    local domain="$1"
    local attempt
    echo -e "Waiting for Let's Encrypt to issue a certificate for ${BOLD}${domain}${NC}..."
    for attempt in $(seq 1 30); do
        if certificate_matches_domain "$domain"; then
            echo -e "${GREEN}✓ HTTPS certificate is ready for ${domain}.${NC}"
            return 0
        fi
        sleep 3
    done
    echo -e "${RED}SSL certificate was not issued for ${domain}.${NC}"
    echo -e "${YELLOW}Caddy log:${NC}"
    $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml logs --tail=40 caddy || true
    return 1
}

# 2. Automated Safety Backup BEFORE pulling any changes
echo -e "${BLUE}▶ [1/6] Creating pre-update safety backup of PostgreSQL database...${NC}"
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
echo -e "\n${BLUE}▶ [2/6] Pulling latest updates from GitHub (main branch)...${NC}"
SCRIPT_HASH_BEFORE=""
if [ -f "$0" ]; then
    SCRIPT_HASH_BEFORE=$(sha256sum "$0" | awk '{print $1}')
fi
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

# The script already running is the copy from before git pull.
# Hand off to the freshly downloaded file so the domain question is actually asked.
case "$0" in
    *update.sh)
        if [ -f "$0" ] && [ -n "$SCRIPT_HASH_BEFORE" ] && [ "${ELINOR_UPDATE_LOADED:-}" != "1" ]; then
            SCRIPT_HASH_AFTER=$(sha256sum "$0" | awk '{print $1}')
            if [ "$SCRIPT_HASH_BEFORE" != "$SCRIPT_HASH_AFTER" ]; then
                echo -e "${YELLOW}Updater itself changed. Continuing with the new script so the domain step is included.${NC}"
                export ELINOR_UPDATE_LOADED=1
                exec bash "$0"
            fi
        fi
        ;;
esac

# 3. Optional domain change. HTTPS is issued by Caddy only after DNS points here.
echo -e "\n${BLUE}▶ [3/6] Domain and SSL...${NC}"
OLD_DOMAIN="${DOMAIN_NAME:-}"
OLD_SSL="n"
if [ -n "$OLD_DOMAIN" ] && [ "${SECURE_SSL_REDIRECT:-false}" = "true" ]; then
    OLD_SSL="y"
fi
DOMAIN_CHANGED="n"
if [ -n "$OLD_DOMAIN" ]; then
    echo -e "Current domain: ${BOLD}https://${OLD_DOMAIN}${NC}"
else
    echo -e "Current access has no public domain (HTTP on port ${APP_PORT:-8010})."
fi

NEW_DOMAIN=""
if [ -e /dev/tty ]; then
    echo -e "Enter a new domain to switch the panel and issue HTTPS, or press Enter to keep this one."
    echo -e "دامنه جدید را وارد کنید، یا برای بدون تغییر Enter بزنید:"
    read -r NEW_DOMAIN < /dev/tty || NEW_DOMAIN=""
else
    echo -e "${YELLOW}No interactive terminal. Keeping the current domain.${NC}"
fi
NEW_DOMAIN=$(normalize_domain "$NEW_DOMAIN")

if [ -n "$NEW_DOMAIN" ] && [ "$NEW_DOMAIN" != "$OLD_DOMAIN" ]; then
    if ! valid_domain "$NEW_DOMAIN"; then
        echo -e "${RED}Error: '${NEW_DOMAIN}' is not a domain name. Example: elinor.example.com${NC}"
        exit 1
    fi
    echo -e "${YELLOW}DNS for ${NEW_DOMAIN} must already point to this server, and ports 80 and 443 must be open.${NC}"
    echo -e "Let's Encrypt will issue the certificate only after that. Continue? (y/n) [Default: n]: "
    read -r confirm_domain < /dev/tty || confirm_domain="n"
    confirm_domain=${confirm_domain:-n}
    if [[ ! "$confirm_domain" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Domain change cancelled. Keeping ${OLD_DOMAIN:-the current HTTP address}.${NC}"
    else
        cp .env "backups/env_before_domain_${STAMP}"
        update_env_var DOMAIN_NAME "$NEW_DOMAIN"
        update_env_var ALLOWED_HOSTS "${NEW_DOMAIN},localhost,127.0.0.1"
        update_env_var CSRF_TRUSTED_ORIGINS "https://${NEW_DOMAIN}"
        update_env_var SECURE_SSL_REDIRECT "true"
        reload_env
        DOMAIN_CHANGED="y"
        echo -e "${GREEN}✓ Domain saved: https://${NEW_DOMAIN}${NC}"
    fi
fi

HAS_SSL="n"
if [ -n "${DOMAIN_NAME:-}" ] && [ -f "compose.prod.yaml" ] && [ "${SECURE_SSL_REDIRECT:-false}" = "true" ]; then
    HAS_SSL="y"
fi

# 4. Rebuild and restart application services
echo -e "\n${BLUE}▶ [4/6] Rebuilding application container with latest code...${NC}"
RECREATE=""
if [ "$DOMAIN_CHANGED" = "y" ]; then
    RECREATE="--force-recreate"
fi

if [ "$HAS_SSL" = "y" ]; then
    echo -e "Rebuilding with production SSL profile (${DOMAIN_NAME})..."
    $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml build web
    echo -e "Restarting services..."
    compose_up "$RECREATE"
else
    echo -e "Rebuilding standard web service..."
    $COMPOSE_CMD build web
    echo -e "Restarting services..."
    compose_up ""
fi

if [ "$DOMAIN_CHANGED" = "y" ]; then
    if ! wait_for_certificate "$DOMAIN_NAME"; then
        echo -e "${YELLOW}Restoring the previous domain so the panel does not stay on a broken HTTPS address.${NC}"
        cp "backups/env_before_domain_${STAMP}" .env
        reload_env
        HAS_SSL="$OLD_SSL"
        DOMAIN_CHANGED="n"
        compose_up "--force-recreate"
        echo -e "${RED}The new domain was not activated.${NC}"
        echo -e "Point the DNS A record to this server, open ports 80 and 443, then run ./update.sh again."
        echo -e "صدور گواهی SSL ناموفق بود. دامنه قبلی برگردانده شد."
    fi
fi

# 5. Apply Database Migrations & Collect Static Files
echo -e "\n${BLUE}▶ [5/6] Applying new database migrations safely...${NC}"
echo -e "Waiting until the container finishes its startup migration..."
ready=0
for _ in $(seq 1 90); do
    if $COMPOSE_CMD exec -T web sh -c 'tr "\0" " " < /proc/1/cmdline | grep -q gunicorn'; then
        ready=1
        break
    fi
    sleep 2
done
if [ "$ready" != "1" ]; then
    echo -e "${YELLOW}Startup is still in progress. Applying migrations anyway.${NC}"
fi
$COMPOSE_CMD exec -T web python manage.py migrate --noinput

echo -e "Collecting static files..."
$COMPOSE_CMD exec -T web python manage.py collectstatic --noinput

# 6. Verify System Health
echo -e "\n${BLUE}▶ [6/6] Verifying system health and integrity...${NC}"
if ! $COMPOSE_CMD exec -T web python manage.py check; then
    echo -e "${RED}The web container is not staying up.${NC}"
    echo -e "${YELLOW}Last web logs:${NC}"
    if [ "${HAS_SSL:-n}" = "y" ]; then
        $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml logs --tail=80 web || true
    else
        $COMPOSE_CMD logs --tail=80 web || true
    fi
    exit 1
fi

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
