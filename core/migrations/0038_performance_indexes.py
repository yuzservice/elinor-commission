from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0037_systemsettings_overtime_hourly_multiplier'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='dailyshiftlog',
            index=models.Index(fields=['date', 'shift'], name='core_dsl_date_shift_idx'),
        ),
        migrations.AddIndex(
            model_name='dailyshiftlog',
            index=models.Index(fields=['status', 'date', 'shift'], name='core_dsl_status_dt_sh_idx'),
        ),
        migrations.AddIndex(
            model_name='lineshiftperformance',
            index=models.Index(fields=['date', 'shift'], name='core_lsp_date_shift_idx'),
        ),
    ]
