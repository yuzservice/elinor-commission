#!/usr/bin/env bash
# ==============================================================================
# اسکریپت نصب و راه‌اندازی آسان سامانه عملکرد و پورسانت الینور با داکر و SSL خودکار
# Elinor Commission System — Automated Docker & SSL Installer
# ==============================================================================

set -e

# رنگ‌ها برای خروجی زیباتر
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${GREEN}${BOLD}"
echo "=================================================================="
echo "    🚀 سامانه عملکرد و پورسانت الینور — نصب آسان با داکر و SSL     "
echo "=================================================================="
echo -e "${NC}"

# ۱. بررسی نیازمندی‌های داکر
echo -e "${BLUE}▶ مرحله ۱: بررسی پیش‌نیازهای سیستم...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}داکر نصب نیست. در حال بررسی امکان نصب خودکار...${NC}"
    if [ -f /etc/debian_version ] || [ -f /etc/lsb-release ]; then
        read -p "آیا مایلید داکر به صورت خودکار نصب شود؟ (y/n): " install_docker
        if [[ "$install_docker" =~ ^[Yy]$ ]]; then
            echo -e "${BLUE}در حال نصب Docker و پلاگین Docker Compose...${NC}"
            sudo apt-get update
            sudo apt-get install -y ca-certificates curl gnupg
            sudo install -m 0755 -d /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
            sudo chmod a+r /etc/apt/keyrings/docker.gpg
            echo \
              "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
              $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
              sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
            sudo apt-get update
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            sudo systemctl enable --now docker
            sudo usermod -aG docker "$USER" 2>/dev/null || true
            echo -e "${GREEN}✓ داکر با موفقیت نصب شد.${NC}"
        else
            echo -e "${RED}خطا: برای ادامه، لطفاً ابتدا داکر را نصب کنید.${NC}"
            exit 1
        fi
    else
        echo -e "${RED}خطا: داکر نصب نیست. لطفاً Docker را نصب کنید و مجدداً این اسکریپت را اجرا نمایید.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Docker در سیستم شناسایی شد.${NC}"
fi

# بررسی دستور docker compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}خطا: Docker Compose یافت نشد.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose آماده است.${NC}"

# ۲. پیکربندی فایل .env و SSL
echo -e "
${BLUE}▶ مرحله ۲: پیکربندی دامنه و امنیت (SSL / HTTPS)...${NC}"

HAS_SSL="n"
DOMAIN_NAME=""
SERVER_IP=""

read -p "آیا مایل به اتصال دامنه و فعال‌سازی رایگان SSL (HTTPS) هستید؟ (y/n) [پیش‌فرض: y]: " ssl_choice
ssl_choice=${ssl_choice:-y}

if [[ "$ssl_choice" =~ ^[Yy]$ ]]; then
    HAS_SSL="y"
    while [ -z "$DOMAIN_NAME" ]; do
        read -p "لطفاً نام دامنه خود را بدون http یا https وارد کنید (مثال: panel.elinor.com): " DOMAIN_NAME
        DOMAIN_NAME=$(echo "$DOMAIN_NAME" | tr -d ' ' | tr '[:upper:]' '[:lower:]')
    done
    echo -e "${GREEN}دامنه تنظیم شد: https://${DOMAIN_NAME}${NC}"
else
    read -p "آدرس IP سرور یا نام هاست (برای دسترسی لوکال اینتر بزنید تا localhost شود): " SERVER_IP
    SERVER_IP=${SERVER_IP:-localhost}
    echo -e "${YELLOW}سیستم بدون SSL و روی پورت 8010 با آدرس http://${SERVER_IP}:8010 راه‌اندازی خواهد شد.${NC}"
fi

# تولید کلیدهای تصادفی امن
SECRET_KEY=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 50 || echo "secret-key-$(date +%s)")
POSTGRES_PASSWORD=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 24 || echo "pgpass-$(date +%s)")

if [ -f .env ]; then
    echo -e "${YELLOW}یک فایل .env از قبل وجود دارد. در حال پشتیبان‌گیری در .env.bak...${NC}"
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
echo -e "${GREEN}✓ تنظیمات امنیتی در فایل .env ذخیره شد.${NC}"

# ۳. بیلد و اجرای کانتینرها
echo -e "
${BLUE}▶ مرحله ۳: بیلد و راه‌اندازی کانتینرهای داکر...${NC}"

if [ "$HAS_SSL" = "y" ]; then
    echo -e "در حال راه‌اندازی سرویس‌های Web، PostgreSQL و Caddy (SSL خودکار)..."
    $COMPOSE_CMD -f compose.yaml -f compose.prod.yaml up -d --build
else
    echo -e "در حال راه‌اندازی سرویس‌های Web و PostgreSQL..."
    $COMPOSE_CMD up -d --build
fi

echo -e "صبر برای راه‌اندازی کامل پایگاه‌داده و اجرای مهاجرت‌ها (Migration)..."
sleep 7

# ۴. ساخت مدیر اولیه و داده‌های پایه
echo -e "
${BLUE}▶ مرحله ۴: تنظیمات کاربران اولیه...${NC}"

read -p "آیا مایل به ایجاد حساب کاربری مدیر اصلی (Superuser) هستید؟ (y/n) [پیش‌فرض: y]: " create_admin
create_admin=${create_admin:-y}
if [[ "$create_admin" =~ ^[Yy]$ ]]; then
    $COMPOSE_CMD exec web python manage.py createsuperuser
fi

read -p "آیا مایل به درج داده‌های تستی و اولیه پیش‌فرض (لاین‌ها، شیفت‌ها، تارگت‌ها) هستید؟ (y/n) [پیش‌فرض: n]: " seed_data
if [[ "$seed_data" =~ ^[Yy]$ ]]; then
    $COMPOSE_CMD exec web python manage.py seed
fi

# ۵. اتمام و نمایش اطلاعات دسترسی
echo -e "
${GREEN}${BOLD}=================================================================="
echo "    🎉 تبریک! سامانه عملکرد و پورسانت الینور با موفقیت نصب شد.    "
echo -e "==================================================================${NC}"

if [ "$HAS_SSL" = "y" ]; then
    echo -e "🔗 نشانی دسترسی سامانه: ${BOLD}https://${DOMAIN_NAME}${NC}"
    echo -e "🔒 گواهی SSL به طور کاملاً خودکار فعال و تمدید می‌شود."
else
    echo -e "🔗 نشانی دسترسی سامانه: ${BOLD}http://${SERVER_IP}:8010${NC}"
fi

echo -e "
برای مشاهده لاگ‌های سیستم:"
echo -e "  ${YELLOW}$COMPOSE_CMD logs -f web${NC}"
echo -e "برای متوقف کردن سامانه:"
echo -e "  ${YELLOW}$COMPOSE_CMD down${NC}"
echo ""
