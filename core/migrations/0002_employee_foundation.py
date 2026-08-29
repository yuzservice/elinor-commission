import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

def migrate_employee_data(apps, schema_editor):
    Employee = apps.get_model("core", "Employee")
    User = apps.get_model("auth", "User")
    for employee in Employee.objects.all().iterator():
        parts = (employee.full_name or "").strip().split(maxsplit=1)
        employee.first_name = parts[0] if parts else "بدون نام"
        employee.last_name = parts[1] if len(parts) > 1 else "—"
        employee.mobile = f"099{employee.pk:08d}"
        employee.primary_department = employee.departments.first()
        if employee.role == "SUPERVISOR":
            employee.role = "MANAGER"
        employee.save(update_fields=["first_name", "last_name", "mobile", "primary_department", "role"])
        User.objects.filter(pk=employee.user_id).update(first_name=employee.first_name, last_name=employee.last_name,
            is_active=employee.is_active, is_staff=employee.role == "MANAGER")

class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [
        migrations.RenameField(model_name="employee", old_name="level", new_name="commission_level"),
        migrations.AddField(model_name="employee", name="first_name", field=models.CharField(default="", max_length=75, verbose_name="نام"), preserve_default=False),
        migrations.AddField(model_name="employee", name="last_name", field=models.CharField(default="", max_length=75, verbose_name="نام خانوادگی"), preserve_default=False),
        migrations.AddField(model_name="employee", name="mobile", field=models.CharField(blank=True, max_length=11, null=True, unique=True, validators=[django.core.validators.RegexValidator("^09\\d{9}$", "شماره موبایل باید ۱۱ رقم و با 09 شروع شود.")], verbose_name="شماره موبایل")),
        migrations.AddField(model_name="employee", name="profile_photo", field=models.ImageField(blank=True, upload_to="profiles/%Y/%m/", verbose_name="عکس پروفایل")),
        migrations.AddField(model_name="employee", name="primary_department", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="primary_employees", to="core.department", verbose_name="بخش اصلی")),
        migrations.AddField(model_name="employee", name="created_at", field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now), preserve_default=False),
        migrations.AddField(model_name="employee", name="updated_at", field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now), preserve_default=False),
        migrations.RunPython(migrate_employee_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name="employee", name="full_name"),
        migrations.AlterField(model_name="employee", name="mobile", field=models.CharField(max_length=11, unique=True, validators=[django.core.validators.RegexValidator("^09\\d{9}$", "شماره موبایل باید ۱۱ رقم و با 09 شروع شود.")], verbose_name="شماره موبایل")),
        migrations.AlterField(model_name="employee", name="role", field=models.CharField(choices=[("MANAGER", "مدیر"), ("EMPLOYEE", "کارمند")], default="EMPLOYEE", max_length=12, verbose_name="نقش")),
        migrations.AlterModelOptions(name="employee", options={"ordering": ["last_name", "first_name", "employee_code"]}),
        migrations.CreateModel(name="SystemSettings", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("panel_name", models.CharField(default="سامانه عملکرد", max_length=120, verbose_name="نام پنل")),
            ("organization_name", models.CharField(default="الینور", max_length=120, verbose_name="نام مجموعه")),
            ("logo", models.ImageField(blank=True, upload_to="branding/", verbose_name="لوگو")),
            ("favicon", models.ImageField(blank=True, upload_to="branding/", verbose_name="فاوآیکون")),
            ("primary_color", models.CharField(default="#237554", max_length=7, validators=[django.core.validators.RegexValidator("^#[0-9A-Fa-f]{6}$", "رنگ باید مانند #237554 باشد.")], verbose_name="رنگ اصلی")),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name="AuditLog", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("action", models.CharField(db_index=True, max_length=80)), ("entity_type", models.CharField(db_index=True, max_length=80)),
            ("entity_id", models.CharField(db_index=True, max_length=80)), ("description", models.TextField(blank=True)),
            ("old_values", models.JSONField(blank=True, default=dict)), ("new_values", models.JSONField(blank=True, default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_logs", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-created_at"]}),
        migrations.CreateModel(name="EmployeeLevelHistory", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reason", models.TextField(blank=True, verbose_name="دلیل")), ("changed_at", models.DateTimeField(auto_now_add=True)),
            ("changed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employee_level_changes", to=settings.AUTH_USER_MODEL)),
            ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="level_history", to="core.employee")),
            ("new_level", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="level_history_to", to="core.commissionlevel")),
            ("previous_level", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="level_history_from", to="core.commissionlevel")),
        ], options={"ordering": ["-changed_at"]}),
    ]
