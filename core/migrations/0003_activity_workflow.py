from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
from django.utils import timezone


def migrate_activity_definitions(apps, schema_editor):
    Category = apps.get_model("core", "ActivityCategory")
    ActivityType = apps.get_model("core", "ActivityType")
    categories = {}
    for code, title, order in [
        ("MAIN_PERFORMANCE", "عملکرد اصلی", 10),
        ("OPERATIONAL_TASK", "وظیفه عملیاتی", 20),
        ("DAILY_CHECKLIST", "چک‌لیست روزانه", 30),
        ("OCCASIONAL_TASK", "فعالیت موردی", 40),
        ("KPI_ONLY", "شاخص بدون اثر مستقیم روی پورسانت", 50),
    ]:
        categories[code] = Category.objects.create(code=code, title=title, sort_order=order)

    for item in ActivityType.objects.all():
        legacy = (item.legacy_category or "").strip()
        if legacy == "فروش اصلی":
            category = categories["MAIN_PERFORMANCE"]
        elif legacy == "وظایف":
            category = categories["OPERATIONAL_TASK"]
        elif legacy == "دسته مسئولیت":
            category = categories["KPI_ONLY"]
        else:
            category = categories["OCCASIONAL_TASK"]
        item.category = category
        item.scoring_method = "FIXED" if item.code in {"M04", "M05"} else "DIRECT_VALUE"
        item.recurrence_type = "OCCASIONAL" if item.recurrence_type == "ADHOC" else item.recurrence_type
        item.created_at = timezone.now()
        item.updated_at = item.created_at
        item.save(update_fields=["category", "scoring_method", "recurrence_type", "created_at", "updated_at"])


def migrate_activities(apps, schema_editor):
    Activity = apps.get_model("core", "Activity")
    History = apps.get_model("core", "ActivityStatusHistory")
    for item in Activity.objects.all():
        if item.status == "NEEDS_EDIT":
            item.status = "NEEDS_REVISION"
        score = (item.value or Decimal("0")) * (item.definition_score_snapshot or Decimal("0"))
        item.calculated_score = score
        item.final_score = score
        item.multiplier_snapshot = Decimal("1")
        item.submitted_at = item.created_at
        item.updated_at = timezone.now()
        item.save(update_fields=["status", "calculated_score", "final_score", "multiplier_snapshot", "submitted_at", "updated_at"])
        actor_id = item.reviewed_by_id or item.submitted_by_id
        History.objects.create(
            activity_id=item.pk,
            previous_status="",
            new_status=item.status,
            actor_id=actor_id,
            note="انتقال خودکار از نسخه قبلی",
        )


def reverse_noop(apps, schema_editor):
    # Schema rollback handles fields; generated categories/history have no safe
    # distinction from subsequently entered business data.
    pass


class Migration(migrations.Migration):
    dependencies = [("core", "0002_employee_foundation")]
    operations = [
        migrations.CreateModel(
            name="ActivityCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="کد")),
                ("title", models.CharField(max_length=120, verbose_name="عنوان")),
                ("description", models.TextField(blank=True, verbose_name="توضیحات")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="ترتیب")),
                ("active", models.BooleanField(default=True, verbose_name="فعال")),
            ],
            options={"ordering": ["sort_order", "title"]},
        ),
        migrations.RenameField(model_name="activitytype", old_name="category", new_name="legacy_category"),
        migrations.RenameField(model_name="activitytype", old_name="points_per_unit", new_name="score_value"),
        migrations.RenameField(model_name="activitytype", old_name="frequency", new_name="recurrence_type"),
        migrations.RenameField(model_name="activitytype", old_name="requires_approval", new_name="requires_manager_approval"),
        migrations.RenameField(model_name="activitytype", old_name="is_active", new_name="active"),
        migrations.AddField(model_name="activitytype", name="category", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="activity_types", to="core.activitycategory", verbose_name="دسته‌بندی")),
        migrations.AddField(model_name="activitytype", name="description", field=models.TextField(blank=True, verbose_name="توضیحات")),
        migrations.AddField(model_name="activitytype", name="scoring_method", field=models.CharField(choices=[("FIXED", "ثابت"), ("QUANTITY_MULTIPLIER", "مقدار × ضریب"), ("DIRECT_VALUE", "مقدار مستقیم")], default="DIRECT_VALUE", max_length=24, verbose_name="روش امتیازدهی")),
        migrations.AddField(model_name="activitytype", name="multiplier", field=models.DecimalField(decimal_places=2, default=1, max_digits=12, verbose_name="ضریب")),
        migrations.AddField(model_name="activitytype", name="is_commission_eligible", field=models.BooleanField(default=True, verbose_name="مشمول پورسانت")),
        migrations.AddField(model_name="activitytype", name="allow_employee_note", field=models.BooleanField(default=True, verbose_name="اجازه توضیح کارمند")),
        migrations.AddField(model_name="activitytype", name="max_daily_submissions", field=models.PositiveIntegerField(blank=True, null=True, verbose_name="حداکثر ثبت روزانه")),
        migrations.AddField(model_name="activitytype", name="minimum_value", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name="حداقل مقدار")),
        migrations.AddField(model_name="activitytype", name="maximum_value", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name="حداکثر مقدار")),
        migrations.AddField(model_name="activitytype", name="all_departments", field=models.BooleanField(default=False, verbose_name="قابل استفاده برای همه بخش‌ها")),
        migrations.AddField(model_name="activitytype", name="sort_order", field=models.PositiveIntegerField(default=0, verbose_name="ترتیب")),
        migrations.AddField(model_name="activitytype", name="created_at", field=models.DateTimeField(auto_now_add=True, null=True)),
        migrations.AddField(model_name="activitytype", name="updated_at", field=models.DateTimeField(auto_now=True, null=True)),
        migrations.AlterField(model_name="activitytype", name="score_value", field=models.DecimalField(decimal_places=2, default=1, max_digits=12, verbose_name="امتیاز ثابت")),
        migrations.AlterField(model_name="activitytype", name="recurrence_type", field=models.CharField(choices=[("DAILY", "روزانه"), ("WEEKLY", "هفتگی"), ("MONTHLY", "ماهانه"), ("OCCASIONAL", "موردی"), ("UNLIMITED", "بدون محدودیت")], default="OCCASIONAL", max_length=12, verbose_name="تناوب")),
        migrations.AlterField(model_name="activitytype", name="requires_manager_approval", field=models.BooleanField(default=True, verbose_name="نیازمند تأیید مدیر")),
        migrations.AlterModelOptions(name="activitytype", options={"ordering": ["sort_order", "title"]}),
        migrations.RunPython(migrate_activity_definitions, reverse_noop),
        migrations.RemoveField(model_name="activitytype", name="legacy_category"),
        migrations.AlterField(model_name="activitytype", name="category", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="activity_types", to="core.activitycategory", verbose_name="دسته‌بندی")),
        migrations.RenameField(model_name="activity", old_name="quantity", new_name="value"),
        migrations.RenameField(model_name="activity", old_name="points_snapshot", new_name="definition_score_snapshot"),
        migrations.RenameField(model_name="activity", old_name="description", new_name="employee_note"),
        migrations.RenameField(model_name="activity", old_name="review_note", new_name="manager_note"),
        migrations.AlterField(model_name="activity", name="employee_note", field=models.TextField(blank=True, verbose_name="توضیحات کارمند")),
        migrations.AlterField(model_name="activity", name="manager_note", field=models.TextField(blank=True, verbose_name="یادداشت مدیر")),
        migrations.AlterField(model_name="activity", name="value", field=models.DecimalField(decimal_places=2, default=1, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))], verbose_name="مقدار")),
        migrations.AlterField(model_name="activity", name="definition_score_snapshot", field=models.DecimalField(decimal_places=2, default=1, max_digits=12, verbose_name="مقدار امتیاز تعریف هنگام ثبت")),
        migrations.AlterField(model_name="activity", name="evidence", field=models.FileField(blank=True, upload_to="evidence/%Y/%m/", verbose_name="مدرک")),
        migrations.AlterField(model_name="activity", name="status", field=models.CharField(choices=[("DRAFT", "پیش‌نویس"), ("PENDING", "در انتظار بررسی"), ("APPROVED", "تأییدشده"), ("REJECTED", "ردشده"), ("NEEDS_REVISION", "نیازمند اصلاح")], default="PENDING", max_length=20, verbose_name="وضعیت")),
        migrations.AddField(model_name="activity", name="multiplier_snapshot", field=models.DecimalField(decimal_places=2, default=1, max_digits=12, verbose_name="ضریب هنگام ثبت")),
        migrations.AddField(model_name="activity", name="calculated_score", field=models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="امتیاز محاسبه‌شده")),
        migrations.AddField(model_name="activity", name="final_score", field=models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="امتیاز نهایی")),
        migrations.AddField(model_name="activity", name="submitted_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="activity", name="updated_at", field=models.DateTimeField(auto_now=True, null=True)),
        migrations.CreateModel(
            name="ActivityStatusHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("previous_status", models.CharField(blank=True, max_length=20)),
                ("new_status", models.CharField(choices=[("DRAFT", "پیش‌نویس"), ("PENDING", "در انتظار بررسی"), ("APPROVED", "تأییدشده"), ("REJECTED", "ردشده"), ("NEEDS_REVISION", "نیازمند اصلاح")], max_length=20)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="core.activity")),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="activity_status_changes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.RunPython(migrate_activities, reverse_noop),
        migrations.AlterField(model_name="activitytype", name="created_at", field=models.DateTimeField(auto_now_add=True)),
        migrations.AlterField(model_name="activitytype", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AlterField(model_name="activity", name="updated_at", field=models.DateTimeField(auto_now=True)),
    ]
