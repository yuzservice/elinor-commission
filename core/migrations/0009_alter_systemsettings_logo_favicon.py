from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_linecommissionrate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='systemsettings',
            name='favicon',
            field=models.FileField(blank=True, upload_to='branding/', verbose_name='فاوآیکون'),
        ),
        migrations.AlterField(
            model_name='systemsettings',
            name='logo',
            field=models.FileField(blank=True, upload_to='branding/', verbose_name='لوگو'),
        ),
    ]
