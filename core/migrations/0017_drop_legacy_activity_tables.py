import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_merge_archive_and_violation_foundation"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DROP TABLE IF EXISTS core_activitystatushistory CASCADE;
            DROP TABLE IF EXISTS core_activity CASCADE;
            DROP TABLE IF EXISTS core_activitytype_departments CASCADE;
            DROP TABLE IF EXISTS core_activitytype CASCADE;
            DROP TABLE IF EXISTS core_activitycategory CASCADE;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="departmentmonthlytarget",
            name="department",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="monthly_targets",
                to="core.department",
                verbose_name="لاین / بخش",
            ),
        ),
    ]
