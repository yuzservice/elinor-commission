from decimal import Decimal
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_department_is_cashier_and_dailyshiftlog_invoice_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="LineActivityType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120, verbose_name="نام فعالیت")),
                ("unit_label", models.CharField(default="عدد", max_length=50, verbose_name="واحد شمارش")),
                (
                    "unit_multiplier",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("1.0"),
                        help_text="مثلاً ۱۰ یعنی هر واحد شمارش = ۱۰ واحد عملکرد در پورسانت",
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                        verbose_name="ضریب تبدیل به واحد عملکرد",
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="ترتیب")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="line_activity_types",
                        to="core.department",
                        verbose_name="لاین / بخش",
                    ),
                ),
            ],
            options={
                "verbose_name": "نوع فعالیت لاین",
                "verbose_name_plural": "انواع فعالیت لاین",
                "ordering": ["sort_order", "title", "pk"],
                "unique_together": {("department", "title")},
            },
        ),
        migrations.CreateModel(
            name="ShiftLogActivityEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField(default=0, verbose_name="تعداد / مقدار")),
                (
                    "unit_multiplier_snapshot",
                    models.DecimalField(decimal_places=2, default=Decimal("1.0"), max_digits=10, verbose_name="ضریب لحظه ثبت"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "activity_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shift_entries",
                        to="core.lineactivitytype",
                        verbose_name="نوع فعالیت",
                    ),
                ),
                (
                    "shift_log",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activity_entries",
                        to="core.dailyshiftlog",
                        verbose_name="کارکرد شیفت",
                    ),
                ),
            ],
            options={
                "verbose_name": "ثبت فعالیت در کارکرد",
                "verbose_name_plural": "ثبت‌های فعالیت در کارکرد",
                "ordering": ["activity_type__sort_order", "activity_type__title", "pk"],
                "unique_together": {("shift_log", "activity_type")},
            },
        ),
    ]
