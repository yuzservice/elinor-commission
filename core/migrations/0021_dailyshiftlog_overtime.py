from decimal import Decimal
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_employee_primary_departments"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailyshiftlog",
            name="has_overtime",
            field=models.BooleanField(default=False, verbose_name="ثبت اضافه‌کاری"),
        ),
        migrations.AddField(
            model_name="dailyshiftlog",
            name="overtime_start_time",
            field=models.TimeField(blank=True, null=True, verbose_name="ساعت شروع اضافه‌کاری"),
        ),
        migrations.AddField(
            model_name="dailyshiftlog",
            name="overtime_end_time",
            field=models.TimeField(blank=True, null=True, verbose_name="ساعت پایان اضافه‌کاری"),
        ),
        migrations.AddField(
            model_name="dailyshiftlog",
            name="overtime_department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="overtime_shift_logs",
                to="core.department",
                verbose_name="لاین اضافه‌کاری",
            ),
        ),
        migrations.AddField(
            model_name="dailyshiftlog",
            name="overtime_hours",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.0"),
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.0")),
                    django.core.validators.MaxValueValidator(Decimal("24.0")),
                ],
                verbose_name="ساعت اضافه‌کاری",
            ),
        ),
        migrations.AddField(
            model_name="dailyshiftlog",
            name="frozen_overtime_share_units",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.0"),
                max_digits=10,
                verbose_name="سهم فریز شده اضافه‌کاری (کالا)",
            ),
        ),
    ]
