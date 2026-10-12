from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0036_convert_monetary_data_to_toman'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='overtime_hourly_multiplier',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.20'),
                help_text='به ازای هر ساعت اضافه‌کاری، این ضریب در مجموع عملکرد روز کارمند ضرب می‌شود (مثلاً 0.20 یعنی ۲۰٪ به ازای هر ساعت).',
                max_digits=4,
                verbose_name='ضریب عملکرد هر ساعت اضافه‌کاری',
            ),
        ),
    ]
