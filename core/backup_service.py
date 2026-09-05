import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
import jdatetime


def get_backups_dir() -> Path:
    backup_dir = Path(settings.BASE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_system_backup(*, actor=None, note="", include_media=True):
    """
    ایجاد فایل فشرده ZIP حاوی:
    1. داده‌های کامل دیتابیس (dumpdata JSON سازگار بین تمام نسخه‌ها)
    2. دامپ SQL مستقیم PostgreSQL (در صورت در دسترس بودن pg_dump)
    3. تمام فایل‌های آپلود شده پوشه media (عکس پرسنل، لوگو و...)
    4. شناسنامه و متادیتای سیستم و نسخه (backup_meta.json)
    """
    from .models import (
        AuditLog,
        CommissionLevel,
        DailyShiftLog,
        Department,
        Employee,
        LineCommissionRate,
        LineShiftPerformance,
        LineTarget,
        Shift,
        SystemSettings,
        Violation,
        ViolationRule,
    )
    from .services import audit

    backup_dir = get_backups_dir()
    now = timezone.now()
    j_now = jdatetime.datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    filename = f"elinor_backup_{timestamp_str}.zip"
    zip_path = backup_dir / filename

    stats = {
        "employees": Employee.objects.count(),
        "departments": Department.objects.count(),
        "shifts": Shift.objects.count(),
        "shift_logs": DailyShiftLog.objects.count(),
        "line_performances": LineShiftPerformance.objects.count(),
        "line_rates": LineCommissionRate.objects.count(),
        "line_targets": LineTarget.objects.count(),
        "violations": Violation.objects.count(),
        "violation_rules": ViolationRule.objects.count(),
        "audit_logs": AuditLog.objects.count(),
    }

    meta = {
        "system_name": "سامانه عملکرد و پورسانت الینور",
        "version": "1.2.0",
        "created_at": now.isoformat(),
        "created_at_jalali": j_now.strftime("%Y/%m/%d %H:%M:%S"),
        "created_by": actor.username if actor else "system",
        "note": note,
        "database_engine": settings.DATABASES["default"]["ENGINE"],
        "stats": stats,
    }

    # ۱. تهیه خروجی داده‌های کامل دیتابیس با dumpdata در قالب JSON
    json_buf = io.StringIO()
    call_command(
        "dumpdata",
        stdout=json_buf,
        natural_foreign=True,
        natural_primary=True,
        indent=2,
        exclude=["contenttypes", "auth.permission"],
    )
    json_dump_str = json_buf.getvalue()

    # ۲. تهیه خروجی SQL خام در صورت وجود ابزار pg_dump
    pg_sql_content = None
    db_conf = settings.DATABASES["default"]
    if "postgresql" in db_conf.get("ENGINE", "") and shutil.which("pg_dump"):
        env = os.environ.copy()
        if db_conf.get("PASSWORD"):
            env["PGPASSWORD"] = str(db_conf["PASSWORD"])
        cmd = [
            "pg_dump",
            "-h", str(db_conf.get("HOST", "localhost")),
            "-p", str(db_conf.get("PORT", "5432")),
            "-U", str(db_conf.get("USER", "elinor")),
            "-d", str(db_conf.get("NAME", "elinor")),
            "--no-owner",
            "--no-privileges",
        ]
        try:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
            if res.returncode == 0 and res.stdout:
                pg_sql_content = res.stdout
        except Exception:
            pass

    # ۳. فشرده‌سازی داخل فایل ZIP
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        zf.writestr("data.json", json_dump_str)
        if pg_sql_content:
            zf.writestr("database.sql", pg_sql_content)

        # فشرده‌سازی فایل‌های پوشه media
        if include_media:
            media_root = Path(settings.MEDIA_ROOT)
            if media_root.exists():
                for root, _, files in os.walk(media_root):
                    for f in files:
                        file_path = Path(root) / f
                        arcname = Path("media") / file_path.relative_to(media_root)
                        zf.write(file_path, arcname=str(arcname))

    if actor:
        audit(
            actor=actor,
            action="backup.created",
            instance=SystemSettings.load(),
            description=f"ایجاد فایل پشتیبان سامانه: {filename}",
            new_values={"filename": filename, "stats": stats, "note": note},
        )

    return zip_path, meta


def list_system_backups() -> list:
    """فهرست تمام فایل‌های پشتیبان موجود در پوشه backups به همراه مشخصات و حجم."""
    backup_dir = get_backups_dir()
    backups = []

    # خواندن فایل‌های ZIP
    for p in sorted(backup_dir.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        size_bytes = p.stat().st_size
        size_mb = round(size_bytes / (1024 * 1024), 2)
        size_display = f"{size_mb} مگابایت" if size_mb >= 1 else f"{round(size_bytes / 1024, 1)} کیلوبایت"
        mtime = timezone.datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.get_current_timezone())
        j_date = jdatetime.datetime.fromgregorian(datetime=mtime).strftime("%Y/%m/%d %H:%M:%S")

        meta = {}
        try:
            with zipfile.ZipFile(p, "r") as zf:
                if "backup_meta.json" in zf.namelist():
                    meta = json.loads(zf.read("backup_meta.json").decode("utf-8"))
        except Exception:
            pass

        backups.append({
            "filename": p.name,
            "type": "ZIP (کامل)",
            "is_zip": True,
            "size_display": size_display,
            "size_bytes": size_bytes,
            "created_at_jalali": meta.get("created_at_jalali", j_date),
            "created_by": meta.get("created_by", "مدیر سیستم"),
            "note": meta.get("note", ""),
            "stats": meta.get("stats", {}),
            "version": meta.get("version", "1.2.0"),
        })

    # خواندن فایل‌های dump قدیمی احتمالی
    for p in sorted(backup_dir.glob("*.dump"), key=lambda x: x.stat().st_mtime, reverse=True):
        size_bytes = p.stat().st_size
        size_mb = round(size_bytes / (1024 * 1024), 2)
        size_display = f"{size_mb} مگابایت" if size_mb >= 1 else f"{round(size_bytes / 1024, 1)} کیلوبایت"
        mtime = timezone.datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.get_current_timezone())
        j_date = jdatetime.datetime.fromgregorian(datetime=mtime).strftime("%Y/%m/%d %H:%M:%S")

        backups.append({
            "filename": p.name,
            "type": "DUMP (دیتابیس)",
            "is_zip": False,
            "size_display": size_display,
            "size_bytes": size_bytes,
            "created_at_jalali": j_date,
            "created_by": "اسکریپت خودکار",
            "note": "پشتیبان خام دیتابیس",
            "stats": {},
            "version": "1.0.0",
        })

    return backups


def get_backup_file_path(filename: str) -> Path:
    """مسیر فایل بکاپ با بررسی امنیت جهت جلوگیری از Path Traversal."""
    safe_name = os.path.basename(filename)
    path = get_backups_dir() / safe_name
    if not path.exists():
        raise ValidationError("فایل پشتیبان مورد نظر یافت نشد.")
    return path


def delete_backup_file(filename: str, *, actor=None) -> bool:
    path = get_backup_file_path(filename)
    if path.exists():
        path.unlink()
        if actor:
            from .models import SystemSettings
            from .services import audit
            audit(
                actor=actor,
                action="backup.deleted",
                instance=SystemSettings.load(),
                description=f"حذف فایل پشتیبان: {filename}",
            )
        return True
    return False


def restore_system_backup(zip_source, *, actor=None) -> dict:
    """
    بازیابی کامل سامانه از فایل ZIP با رعایت اصول حرفه‌ای:
    1. ایجاد بکاپ خودکار و اضطراری از وضعیت فعلی پیش از اعمال تغییر
    2. بازیابی دیتابیس (تزریق داده‌ها)
    3. اجرای خودکار مهاجرت‌ها (migrate) جهت ارتقای داده‌های قدیمی به آخرین نسخه اسکیما
    4. بازگردانی فایل‌های آپلودشده media
    5. اطمینان از دسترسی کامل مدیر جاری پس از بازیابی
    """
    from .models import SystemSettings
    from .services import audit

    if hasattr(zip_source, "read"):
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        for chunk in zip_source.chunks():
            temp_zip.write(chunk)
        temp_zip.close()
        zip_path = Path(temp_zip.name)
        cleanup_temp = True
    else:
        zip_path = Path(zip_source)
        cleanup_temp = False

    try:
        if not zipfile.is_zipfile(zip_path):
            raise ValidationError("فایل انتخابی یک فایل فشرده ZIP معتبر نیست.")

        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            if "data.json" not in namelist and "database.sql" not in namelist:
                raise ValidationError("فایل پشتیبان فاقد داده‌های معتبر پایگاه‌داده (data.json یا database.sql) است.")

            meta = {}
            if "backup_meta.json" in namelist:
                try:
                    meta = json.loads(zf.read("backup_meta.json").decode("utf-8"))
                except Exception:
                    meta = {}

        # گام ۱: پشتیبان‌گیری خودکار و اضطراری از داده‌های فعلی پیش از هر دستکاری
        try:
            create_system_backup(actor=actor, note="پشتیبان‌گیری خودکار پیش از اجرای عملیات بازیابی (Restore)")
        except Exception:
            pass

        # گام ۲: بازیابی داده‌های دیتابیس
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            db_conf = settings.DATABASES["default"]
            restored_via_sql = False

            # الف) اگر دیتابیس PostgreSQL است و psql موجود است، ابتدا تلاش با فایل SQL خام
            if "database.sql" in namelist and "postgresql" in db_conf.get("ENGINE", "") and shutil.which("psql"):
                sql_content = zf.read("database.sql")
                env = os.environ.copy()
                if db_conf.get("PASSWORD"):
                    env["PGPASSWORD"] = str(db_conf["PASSWORD"])
                cmd = [
                    "psql",
                    "-h", str(db_conf.get("HOST", "localhost")),
                    "-p", str(db_conf.get("PORT", "5432")),
                    "-U", str(db_conf.get("USER", "elinor")),
                    "-d", str(db_conf.get("NAME", "elinor")),
                ]
                try:
                    prep_cmd = cmd + ["-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"]
                    subprocess.run(prep_cmd, env=env, check=True, capture_output=True, timeout=60)
                    subprocess.run(cmd, input=sql_content, env=env, check=True, capture_output=True, timeout=180)
                    restored_via_sql = True
                except Exception:
                    restored_via_sql = False

            # ب) در غیر این صورت یا روش استاندارد Django: تخلیه و بارگذاری داده‌های JSON
            if not restored_via_sql and "data.json" in namelist:
                call_command("flush", interactive=False, reset_sequences=True)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="wb") as f_json:
                    f_json.write(zf.read("data.json"))
                    f_json_path = f_json.name
                try:
                    call_command("loaddata", f_json_path)
                finally:
                    if os.path.exists(f_json_path):
                        os.unlink(f_json_path)

            # گام ۳ (بسیار حیاتی برای ارتقا بین نسخه‌ها):
            # اجرای migrate برای تطبیق ساختار دیتابیس نسخه قبلی با نسخه فعلی برنامه
            call_command("migrate", interactive=False)

            # گام ۴: بازیابی فایل‌های media
            media_root = Path(settings.MEDIA_ROOT)
            media_root.mkdir(parents=True, exist_ok=True)
            for member in namelist:
                if member.startswith("media/") and not member.endswith("/"):
                    rel_path = member[len("media/"):]
                    target_file = media_root / rel_path
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target_file, "wb") as dst:
                        shutil.copyfileobj(src, dst)

        # گام ۵: اطمینان از دسترسی کامل مدیر جاری
        if actor:
            from django.contrib.auth.models import User
            current_user = User.objects.filter(username=actor.username).first()
            if current_user:
                from .decorators import get_or_create_manager_employee
                get_or_create_manager_employee(current_user)

            audit(
                actor=actor,
                action="backup.restored",
                instance=SystemSettings.load(),
                description=f"بازیابی موفقیت‌آمیز اطلاعات سامانه از فایل پشتیبان",
                new_values={"source": getattr(zip_source, "name", str(zip_path)), "meta": meta},
            )

        return meta
    finally:
        if cleanup_temp and os.path.exists(zip_path):
            try:
                os.unlink(zip_path)
            except Exception:
                pass
