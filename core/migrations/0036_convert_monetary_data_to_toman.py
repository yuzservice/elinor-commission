from django.db import migrations


def convert_amounts_to_toman(apps, schema_editor):
    """
    کسر یک صفر (تقسیم بر ۱۰) فقط از مبالغ پورسانت پرداخت/فریز شده برای کارکنان.
    ضرایب و نرخ‌ها دست‌نخورده باقی می‌مانند.
    """
    DailyShiftLog = apps.get_model("core", "DailyShiftLog")
    for log in DailyShiftLog.objects.all():
        updated_fields = []
        if log.frozen_commission_amount:
            log.frozen_commission_amount = int(round(log.frozen_commission_amount / 10))
            updated_fields.append("frozen_commission_amount")

        if log.frozen_snapshot_data and isinstance(log.frozen_snapshot_data, dict):
            snap = dict(log.frozen_snapshot_data)
            if "total_commission" in snap and isinstance(snap["total_commission"], (int, float)):
                snap["total_commission"] = int(round(snap["total_commission"] / 10))

            def _scale_commission(info):
                if not isinstance(info, dict):
                    return
                # فقط مبالغ پورسانت بر ۱۰ تقسیم می‌شوند، ضرایب (rate_per_unit) تغییر نمی‌کنند.
                if "commission" in info and isinstance(info["commission"], (int, float)):
                    info["commission"] = int(round(info["commission"] / 10))

            _scale_commission(snap.get("main_info"))
            _scale_commission(snap.get("activity_info"))
            _scale_commission(snap.get("overtime_info"))
            for s in snap.get("support_infos", []) or []:
                _scale_commission(s)

            log.frozen_snapshot_data = snap
            updated_fields.append("frozen_snapshot_data")

        if updated_fields:
            log.save(update_fields=updated_fields)


def convert_amounts_to_rial(apps, schema_editor):
    DailyShiftLog = apps.get_model("core", "DailyShiftLog")
    for log in DailyShiftLog.objects.all():
        updated_fields = []
        if log.frozen_commission_amount:
            log.frozen_commission_amount = log.frozen_commission_amount * 10
            updated_fields.append("frozen_commission_amount")

        if log.frozen_snapshot_data and isinstance(log.frozen_snapshot_data, dict):
            snap = dict(log.frozen_snapshot_data)
            if "total_commission" in snap and isinstance(snap["total_commission"], (int, float)):
                snap["total_commission"] = int(snap["total_commission"] * 10)

            def _scale_commission_rev(info):
                if not isinstance(info, dict):
                    return
                if "commission" in info and isinstance(info["commission"], (int, float)):
                    info["commission"] = int(info["commission"] * 10)

            _scale_commission_rev(snap.get("main_info"))
            _scale_commission_rev(snap.get("activity_info"))
            _scale_commission_rev(snap.get("overtime_info"))
            for s in snap.get("support_infos", []) or []:
                _scale_commission_rev(s)

            log.frozen_snapshot_data = snap
            updated_fields.append("frozen_snapshot_data")

        if updated_fields:
            log.save(update_fields=updated_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_alter_monetary_fields_to_toman'),
    ]

    operations = [
        migrations.RunPython(convert_amounts_to_toman, convert_amounts_to_rial),
    ]
