from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_cleanup_orphaned_users"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="card_number",
            field=models.CharField(
                blank=True,
                default="",
                help_text="شماره کارت ۱۶ رقمی جهت واریز و تسویه پورسانت",
                max_length=24,
                verbose_name="شماره کارت بانکی",
            ),
        ),
    ]
