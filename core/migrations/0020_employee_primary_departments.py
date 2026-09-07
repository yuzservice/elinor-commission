from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_employee_card_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="primary_departments",
            field=models.ManyToManyField(
                blank=True,
                related_name="multi_primary_employees",
                to="core.department",
                verbose_name="لاین‌های اصلی",
            ),
        ),
    ]
