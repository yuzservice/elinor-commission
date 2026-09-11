from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_dailyshiftlog_overtime"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="is_cashier",
            field=models.BooleanField(default=False, verbose_name="لاین صندوقدار (ثبت مستقیم فاکتور)"),
        ),
        migrations.AddField(
            model_name="dailyshiftlog",
            name="invoice_count",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="تعداد فاکتورهای صادرشده"),
        ),
    ]
