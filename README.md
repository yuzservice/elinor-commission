# سامانه عملکرد و پورسانت کارکنان الینور

سامانه فارسی ثبت کارکرد شیفت، فروش لاین‌ها، تخلفات و محاسبه شفاف پورسانت. محیط توسعه Mac و استقرار Ubuntu از یک Docker Compose و یک PostgreSQL استفاده می‌کنند.

## امکانات MVP

- ورود امن و سه نقش مدیر، سرپرست و کارمند
- کارکنان چندبخشی و سطح‌های A تا D
- ثبت کارکرد روزانه، لاین اصلی و چند بازه دقیق لاین کمکی
- ثبت فروش روزانه لاین‌ها و محاسبه سهم زمانی کارکنان
- ثبت تخلف با امتیاز پلکانی سه مرتبه
- قوانین قابل تنظیم سطح، ضریب لاین، تخلف و تارگت
- داشبورد شخصی و داشبورد مدیریت
- migration، seed قابل اجرای مجدد، تست، health check و فایل‌های بکاپ/ریستور

## ماژول کاربران و کارکنان

پنل سفارشی مدیریت کارکنان از `/management/employees/` در دسترس مدیر است. این ماژول شامل ساخت و ویرایش اتمیک User/Employee، جستجو و فیلتر، بخش اصلی و چندبخشی، Levelهای مستقل، تاریخچه تغییر Level، فعال/غیرفعال‌سازی هماهنگ با Login، بازنشانی رمز و Audit Log است.

کارمند از `/profile/` فقط پروفایل خودش را می‌بیند و تنها می‌تواند عکس و رمز خودش را تغییر دهد. تنظیم نام پنل، مجموعه، لوگو، favicon و رنگ اصلی از `/management/settings/branding/` انجام می‌شود. نقش‌های فعال سیستم فقط `Manager` و `Employee` هستند.

مسیرهای اصلی این مرحله:

- `/management/employees/` — فهرست کارکنان
- `/management/employees/create/` — ساخت کارمند
- `/management/employees/<id>/` — پرونده مدیریتی
- `/management/employees/<id>/edit/` — ویرایش
- `/management/employees/<id>/password/` — بازنشانی رمز
- `/management/settings/branding/` — تنظیمات برند
- `/profile/` — پروفایل شخصی
- `/profile/photo/` و `/profile/password/` — عکس و رمز شخصی

عکس‌ها در Local توسط Django سرو می‌شوند. روی Ubuntu مقدار `SERVE_MEDIA=false` قرار دهید و مسیر `/media/` را با Nginx/Caddy یا object storage ارائه کنید.

ماژول قدیمی «فعالیت‌ها» کامل از برنامه حذف شده است. ورودی محاسبات از کارکرد شیفت و فروش لاین‌ها می‌آید و تخلفات به‌صورت مستقل در کسورات باقی مانده‌اند.

## نصب و راه‌اندازی آسان با یک دستور (Easy Install with Docker & SSL)

برای راه‌اندازی کامل و خودکار سامانه روی سرور Ubuntu یا سیستم محلی، اسکریپت نصب خودکار را اجرا کنید:

```bash
chmod +x install.sh
./install.sh
```

این اسکریپت به صورت تعاملی و خودکار:
۱. نصب بودن Docker و Docker Compose را بررسی می‌کند (و در صورت نیاز روی اوبونتو نصب می‌نماید).
۲. در صورت تمایل شما، دامنه را متصل و گواهی رایگان **SSL / HTTPS** را به صورت کاملاً خودکار و دائمی فعال می‌کند.
۳. کلیدهای امنیتی تصادفی و قوی تولید کرده و فایل `.env` را ایجاد می‌نماید.
۴. تمامی کانتینرها، پایگاه‌داده PostgreSQL و مهاجرت‌ها را بالا می‌آورد.
۵. امکان ساخت حساب مدیر اصلی (Superuser) و بارگذاری داده‌های اولیه را فراهم می‌سازد.

## اجرای دستی روی Mac

پیش‌نیاز فقط Docker Desktop است.

```bash
cp .env.example .env
# مقادیر SECRET_KEY و POSTGRES_PASSWORD را در .env تغییر دهید
docker compose up -d --build
docker compose exec web python manage.py seed
```

سپس [http://localhost:8010](http://localhost:8010) را باز کنید. کاربران نمونه `manager`، `supervisor`، `fatemeh`، `mahsa` و `maryam` هستند و رمز اولیه همگی `Elinor123!` است. این رمزها فقط برای نسخه محلی‌اند و باید عوض شوند.

این Compose عمداً با نام مستقل `elinor-commission` اجرا می‌شود و از پورت `8010` استفاده می‌کند؛ بنابراین با پروژه جداگانه `Elinor CRM`، شبکه آن و volume دیتابیس آن تداخل ندارد. برای کنترل همیشه دستور `docker compose ls` را اجرا کنید و مطمئن شوید هر دو پروژه با نام جدا دیده می‌شوند.

برای توسعه با بارگذاری خودکار تغییرات:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

## دستورهای روزمره

```bash
docker compose logs -f web
docker compose exec web python manage.py test
docker compose exec web python manage.py createsuperuser
docker compose down
```

تغییر مدل دیتابیس:

```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

فایل migration جدید را همراه کد در Git ثبت کنید.

## بکاپ و ریستور

اسکریپت‌ها متغیرهای `.env` را مصرف می‌کنند. پیش از اجرا در shell بارگذاری‌شان کنید:

```bash
set -a; source .env; set +a
chmod +x scripts/*.sh
./scripts/backup.sh
./scripts/restore.sh backups/elinor_YYYYMMDD_HHMMSS.dump
```

ریستور دیتابیس فعلی را جایگزین می‌کند؛ قبل از آن یک بکاپ تازه بگیرید. فایل‌های آپلودشده در volume جدا هستند و باید مستقل آرشیو شوند:

```bash
docker run --rm -v elinor_media_data:/data -v "$PWD/backups":/backup alpine tar czf /backup/media.tar.gz -C /data .
```

## استقرار روی Ubuntu

1. Docker Engine و Compose plugin را نصب کنید.
2. repository را clone و `.env.example` را به `.env` کپی کنید.
3. `DEBUG=false`، یک `SECRET_KEY` طولانی، رمز قوی دیتابیس، دامنه در `ALLOWED_HOSTS` و نشانی HTTPS در `CSRF_TRUSTED_ORIGINS` بگذارید.
4. برنامه را اجرا کنید: `docker compose up -d --build`.
5. یک reverse proxy مانند Caddy یا Nginx جلوی پورت 8000 قرار دهید و TLS فعال کنید.
6. پس از اطمینان از HTTPS، `SECURE_SSL_REDIRECT=true` کنید و سرویس web را دوباره بسازید.
7. با cron روزانه `scripts/backup.sh` اجرا و نسخه‌ها را به فضای دیگری منتقل کنید.

برای به‌روزرسانی بدون تغییر مسیر اجرا:

```bash
git pull --ff-only
docker compose up -d --build
docker compose exec web python manage.py test
```

مهاجرت‌ها در شروع کانتینر به‌طور خودکار اجرا می‌شوند. برای محیط پرترافیک، اجرای migration را به مرحله مستقل release تبدیل کنید.

## Git و GitHub

فایل `.env`، بکاپ، آپلود و خروجی‌های محلی عمداً ignore شده‌اند. روند پیشنهادی:

```bash
git checkout -b feature/my-change
git add .
git commit -m "feat: describe the change"
git push -u origin feature/my-change
```

هر تغییر از طریق branch و pull request، همراه migration و تست مرتبط وارد شاخه اصلی شود. هیچ secret یا فایل بکاپی را commit نکنید.

## ساختار پروژه

- `core/`: مدل کسب‌وکار، فرم‌ها، محاسبات، دسترسی‌ها و تست‌ها
- `config/`: تنظیمات و ورودی وب
- `templates/` و `static/`: رابط فارسی واکنش‌گرا
- `scripts/`: startup، بکاپ و ریستور
- `compose.yaml`: اجرای یکسان production-like
- `compose.dev.yaml`: override فقط برای توسعه زنده

## نکات مرحله بعد

برای production نهایی پیشنهاد می‌شود object storage برای مدارک، ثبت audit log تغییر قوانین، بستن دوره حقوق، خروجی Excel/PDF، اعلان‌ها و بکاپ خارج از سرور افزوده شود. قاعده «ضریب صبح» و اتصال دقیق بن تارگت نیز باید با داده واقعی نهایی شود.
