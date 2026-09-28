from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0024_remove_legacy_cashier_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="lineactivitytype",
                    name="count_method",
                    field=models.CharField(
                        choices=[("QUANTITY", "ورود عدد"), ("CHECKMARK", "تیک انجام‌شده")],
                        default="QUANTITY",
                        max_length=20,
                        verbose_name="نحوه ثبت در کارکرد",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE core_lineactivitytype
                    ADD COLUMN IF NOT EXISTS count_method varchar(20) NOT NULL DEFAULT 'QUANTITY';
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
