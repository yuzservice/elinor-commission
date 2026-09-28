from decimal import Decimal

from django.db import migrations


def migrate_cashier_to_line_activities(apps, schema_editor):
    Department = apps.get_model("core", "Department")
    LineActivityType = apps.get_model("core", "LineActivityType")
    DailyShiftLog = apps.get_model("core", "DailyShiftLog")
    ShiftLogActivityEntry = apps.get_model("core", "ShiftLogActivityEntry")

    for dept in Department.objects.filter(is_cashier=True):
        activity, _ = LineActivityType.objects.get_or_create(
            department=dept,
            title="فاکتور صادرشده",
            defaults={
                "unit_label": "فاکتور",
                "unit_multiplier": Decimal("1.0"),
                "sort_order": 0,
                "is_active": True,
            },
        )
        logs = DailyShiftLog.objects.filter(
            main_department=dept,
            invoice_count__isnull=False,
        ).exclude(invoice_count=0)
        for log in logs:
            ShiftLogActivityEntry.objects.update_or_create(
                shift_log=log,
                activity_type=activity,
                defaults={
                    "quantity": log.invoice_count,
                    "unit_multiplier_snapshot": Decimal("1.0"),
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_line_activity_types"),
    ]

    operations = [
        migrations.RunPython(migrate_cashier_to_line_activities, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="dailyshiftlog",
            name="invoice_count",
        ),
        migrations.RemoveField(
            model_name="department",
            name="is_cashier",
        ),
    ]
