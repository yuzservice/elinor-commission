from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("core", "0010_dailyshiftlog_support_departments")]

    operations = [
        migrations.AlterField(
            model_name="dailyshiftlog", name="main_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("6.0"), max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal("0.5")), django.core.validators.MaxValueValidator(Decimal("24.0"))], verbose_name="ساعت در لاین اصلی"),
        ),
        migrations.AlterField(
            model_name="dailyshiftlog", name="support_hours",
            field=models.DecimalField(blank=True, decimal_places=2, default=Decimal("0.0"), max_digits=5, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0.0")), django.core.validators.MaxValueValidator(Decimal("24.0"))], verbose_name="مجموع ساعت در لاین‌های کمکی"),
        ),
        migrations.AlterField(
            model_name="dailyshiftlog", name="total_hours",
            field=models.DecimalField(decimal_places=2, default=Decimal("6.0"), max_digits=5, verbose_name="مجموع ساعت کار"),
        ),
        migrations.CreateModel(
            name="SupportLineInterval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_time", models.TimeField(verbose_name="ساعت شروع")),
                ("end_time", models.TimeField(verbose_name="ساعت پایان")),
                ("duration_minutes", models.PositiveIntegerField(editable=False, verbose_name="مدت (دقیقه)")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="support_intervals", to="core.department", verbose_name="لاین مقصد")),
                ("shift_log", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="support_intervals", to="core.dailyshiftlog", verbose_name="کارکرد شیفت")),
            ],
            options={"verbose_name": "بازه کمکی", "verbose_name_plural": "بازه‌های کمکی", "ordering": ["start_time", "pk"]},
        ),
    ]
