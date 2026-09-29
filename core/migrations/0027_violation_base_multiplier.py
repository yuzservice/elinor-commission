from django.core.validators import MinValueValidator
from django.db import migrations, models


def copy_base_multiplier(apps, schema_editor):
    ViolationRule = apps.get_model("core", "ViolationRule")
    for rule in ViolationRule.objects.all():
        rule.base_multiplier = rule.first_points or 1
        rule.all_departments = True
        rule.second_points = rule.base_multiplier * 2
        rule.third_points = rule.base_multiplier * 3
        rule.save(update_fields=["base_multiplier", "all_departments", "second_points", "third_points"])
        rule.departments.clear()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_global_line_activities"),
    ]

    operations = [
        migrations.AddField(
            model_name="violationrule",
            name="base_multiplier",
            field=models.PositiveIntegerField(
                default=1,
                help_text="امتیاز = ضریب پایه × مرتبه تکرار در همان ماه. مرتبه از ۳ بیشتر حساب نمی‌شود.",
                verbose_name="ضریب پایه",
            ),
        ),
        migrations.RunPython(copy_base_multiplier, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="violation",
            name="occurrence",
            field=models.PositiveSmallIntegerField(
                validators=[MinValueValidator(1)],
                verbose_name="مرتبه",
            ),
        ),
    ]
