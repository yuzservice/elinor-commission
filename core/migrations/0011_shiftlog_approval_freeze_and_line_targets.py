from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal

def approve_existing_shift_logs(apps, schema_editor):
    DailyShiftLog = apps.get_model("core", "DailyShiftLog")
    DailyShiftLog.objects.filter(status="PENDING").update(status="APPROVED")

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_dailyshiftlog_support_departments'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='department',
            options={'ordering': ['name'], 'verbose_name': 'لاین / بخش', 'verbose_name_plural': 'لاین‌ها و بخش‌ها'},
        ),
        migrations.AddField(
            model_name='department',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='department',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='frozen_commission_amount',
            field=models.PositiveBigIntegerField(default=0, verbose_name='مبلغ پورسانت فریز شده (ریال)'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='frozen_main_share_units',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.0'), max_digits=10, verbose_name='سهم فریز شده لاین اصلی (کالا)'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='frozen_snapshot_data',
            field=models.JSONField(blank=True, default=dict, verbose_name='جزئیات فریز شده محاسبات شیفت'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='frozen_support_share_units',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.0'), max_digits=10, verbose_name='سهم فریز شده لاین‌های کمکی (کالا)'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='frozen_total_units_share',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.0'), max_digits=10, verbose_name='مجموع سهم فریز شده کالا'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='is_frozen',
            field=models.BooleanField(default=False, verbose_name='محاسبات فریز شده'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='manager_note',
            field=models.TextField(blank=True, verbose_name='یادداشت / بازخورد مدیر'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='زمان بررسی'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='reviewed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_shift_logs', to=settings.AUTH_USER_MODEL, verbose_name='بررسی‌کننده'),
        ),
        migrations.AddField(
            model_name='dailyshiftlog',
            name='status',
            field=models.CharField(choices=[('PENDING', 'در انتظار تأیید مدیر'), ('APPROVED', 'تأییدشده و واریز نهایی'), ('REJECTED', 'ردشده')], db_index=True, default='PENDING', max_length=20, verbose_name='وضعیت تأیید'),
        ),
        migrations.CreateModel(
            name='DepartmentMonthlyTarget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year_month', models.CharField(db_index=True, help_text='فرمت ۱۴۰۵/۰۶', max_length=7, validators=[django.core.validators.RegexValidator(r'^\d{4}/\d{2}$', 'فرمت تاریخ باید به‌صورت ۱۴۰۵/۰۶ باشد.')], verbose_name='ماه و سال شمسی')),
                ('target_units', models.PositiveIntegerField(default=0, verbose_name='تارگت تعداد فروش کالا')),
                ('target_sales_amount', models.PositiveBigIntegerField(blank=True, default=0, verbose_name='تارگت مبلغ فروش لاین (ریال)')),
                ('target_commission_points', models.PositiveBigIntegerField(blank=True, default=0, verbose_name='تارگت پورسانت ناخالص لاین (ریال)')),
                ('reward_amount', models.PositiveBigIntegerField(blank=True, default=0, verbose_name='پاداش دستیابی به تارگت لاین (ریال)')),
                ('description', models.TextField(blank=True, verbose_name='توضیحات و اهداف شیفت/لاین برای پرسنل')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_department_targets', to=settings.AUTH_USER_MODEL, verbose_name='تعیین‌کننده')),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_targets', to='core.department', verbose_name='لاین / بخش')),
            ],
            options={
                'verbose_name': 'تارگت ماهانه لاین',
                'verbose_name_plural': 'تارگت‌های ماهانه لاین‌ها',
                'ordering': ['-year_month', 'department__name'],
                'unique_together': {('year_month', 'department')},
            },
        ),
        migrations.RunPython(
            approve_existing_shift_logs,
            migrations.RunPython.noop,
        ),
    ]
