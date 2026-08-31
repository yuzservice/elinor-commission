from django.db import migrations, models


def snapshot_existing_violations(apps, schema_editor):
    Violation = apps.get_model("core", "Violation")
    for violation in Violation.objects.select_related("rule").iterator():
        rule = violation.rule
        violation.rule_snapshot = {
            "rule_id": rule.pk,
            "code": rule.code,
            "title": rule.title,
            "occurrence": violation.occurrence,
            "points": violation.points_snapshot,
            "first_points": rule.first_points,
            "second_points": rule.second_points,
            "third_points": rule.third_points,
        }
        violation.save(update_fields=["rule_snapshot"])


class Migration(migrations.Migration):
    dependencies = [("core", "0014_merge_support_intervals_and_line_targets")]

    operations = [
        migrations.AddField(
            model_name="violationrule",
            name="all_departments",
            field=models.BooleanField(default=True, verbose_name="قابل استفاده برای همه لاین‌ها"),
        ),
        migrations.AddField(
            model_name="violationrule",
            name="recurrence_window",
            field=models.CharField(
                choices=[
                    ("SAME_MONTH", "همان ماه"),
                    ("ROLLING_30_DAYS", "۳۰ روز گذشته"),
                    ("MANUAL_PERIOD", "دوره قابل تنظیم"),
                ],
                default="SAME_MONTH",
                help_text="این گزینه زیرساخت مدیریتی است؛ محاسبه خودکار تکرار تا نهایی‌شدن قانون کسب‌وکار فعال نمی‌شود.",
                max_length=20,
                verbose_name="بازه محاسبه تکرار",
            ),
        ),
        migrations.AddField(
            model_name="violationrule",
            name="departments",
            field=models.ManyToManyField(blank=True, related_name="violation_rules", to="core.department"),
        ),
        migrations.AddField(
            model_name="violation",
            name="rule_snapshot",
            field=models.JSONField(blank=True, default=dict, verbose_name="نسخه قانون هنگام ثبت"),
        ),
        migrations.RunPython(snapshot_existing_violations, migrations.RunPython.noop),
    ]
