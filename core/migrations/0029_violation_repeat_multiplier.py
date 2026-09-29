from django.db import migrations, models


def backfill_repeat_multiplier(apps, schema_editor):
    ViolationRule = apps.get_model("core", "ViolationRule")
    for rule in ViolationRule.objects.all():
        base = rule.base_multiplier or rule.first_points or 1
        second = rule.second_points or (base * 2)
        repeat = max(1, round(second / base)) if base else 2
        rule.repeat_multiplier = repeat
        rule.save(update_fields=["repeat_multiplier"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_align_activity_and_violation_help"),
    ]

    operations = [
        migrations.AddField(
            model_name="violationrule",
            name="repeat_multiplier",
            field=models.PositiveIntegerField(
                default=2,
                help_text="بار دوم = ضریب × این عدد. بار سوم و بعد = همان نتیجه × این عدد دوباره.",
                verbose_name="چند برابر در تکرار",
            ),
        ),
        migrations.RunPython(backfill_repeat_multiplier, migrations.RunPython.noop),
    ]
