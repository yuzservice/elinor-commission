from django.db import migrations, models
from decimal import Decimal
import django.core.validators


def copy_legacy_support_departments(apps, schema_editor):
    DailyShiftLog = apps.get_model("core", "DailyShiftLog")
    # Check if support_department field exists on the model at this migration step
    for log in DailyShiftLog.objects.filter(has_support_line=True, support_department__isnull=False).iterator():
        log.support_departments.add(log.support_department)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_alter_systemsettings_logo_favicon'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailyshiftlog',
            name='support_departments',
            field=models.ManyToManyField(blank=True, related_name='support_shift_logs', to='core.department', verbose_name='لاین‌های کمکی'),
        ),
        migrations.AlterField(
            model_name='dailyshiftlog',
            name='support_hours',
            field=models.DecimalField(blank=True, decimal_places=1, default=Decimal('0.0'), max_digits=4, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.0')), django.core.validators.MaxValueValidator(Decimal('24.0'))], verbose_name='مجموع ساعت در لاین‌های کمکی'),
        ),
        migrations.RunPython(
            copy_legacy_support_departments,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='dailyshiftlog',
            name='support_department',
        ),
    ]
