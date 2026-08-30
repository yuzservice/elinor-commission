from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0011_supportlineinterval")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="ActivityStatusHistory"),
                migrations.DeleteModel(name="Activity"),
                migrations.DeleteModel(name="ActivityType"),
                migrations.DeleteModel(name="ActivityCategory"),
            ],
        ),
    ]
