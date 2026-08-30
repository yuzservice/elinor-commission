from decimal import Decimal
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_shift_and_employee_shift'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyShiftLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='تاریخ کارکرد')),
                ('main_hours', models.DecimalField(decimal_places=1, default=Decimal('6.0'), max_digits=4, validators=[django.core.validators.MinValueValidator(Decimal('0.5')), django.core.validators.MaxValueValidator(Decimal('24.0'))], verbose_name='ساعت در لاین اصلی')),
                ('has_support_line', models.BooleanField(default=False, verbose_name='حضور در لاین کمکی')),
                ('support_hours', models.DecimalField(blank=True, decimal_places=1, default=Decimal('0.0'), max_digits=4, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.0')), django.core.validators.MaxValueValidator(Decimal('24.0'))], verbose_name='ساعت در لاین کمکی')),
                ('total_hours', models.DecimalField(decimal_places=1, default=Decimal('6.0'), max_digits=4, verbose_name='مجموع ساعت کار')),
                ('employee_note', models.TextField(blank=True, verbose_name='یادداشت کارمند')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shift_logs', to='core.employee', verbose_name='کارمند')),
                ('main_department', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='main_shift_logs', to='core.department', verbose_name='لاین اصلی')),
                ('shift', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='shift_logs', to='core.shift', verbose_name='شیفت')),
                ('support_department', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_shift_logs', to='core.department', verbose_name='لاین کمکی')),
            ],
            options={
                'verbose_name': 'کارکرد روزانه شیفت',
                'verbose_name_plural': 'کارکردهای روزانه شیفت',
                'ordering': ['-date', '-created_at'],
                'unique_together': {('employee', 'date', 'shift')},
            },
        ),
    ]
