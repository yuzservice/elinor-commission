from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0006_dailyshiftlog'),
    ]

    operations = [
        migrations.CreateModel(
            name='LineShiftPerformance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='تاریخ فروش')),
                ('sold_units', models.PositiveIntegerField(default=0, verbose_name='تعداد کالای فروخته‌شده')),
                ('sales_amount', models.PositiveBigIntegerField(blank=True, default=0, verbose_name='مبلغ فروش (ریال)')),
                ('description', models.TextField(blank=True, verbose_name='توضیحات / یادداشت مدیر')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='shift_performances', to='core.department', verbose_name='لاین / بخش')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recorded_line_performances', to=settings.AUTH_USER_MODEL, verbose_name='ثبت‌کننده')),
                ('shift', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='line_performances', to='core.shift', verbose_name='شیفت')),
            ],
            options={
                'verbose_name': 'عملکرد فروش لاین در شیفت',
                'verbose_name_plural': 'عملکرد فروش لاین‌ها در شیفت',
                'ordering': ['-date', 'shift__sort_order', 'department__name'],
                'unique_together': {('date', 'shift', 'department')},
            },
        ),
    ]
