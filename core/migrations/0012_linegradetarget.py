from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_shiftlog_approval_freeze_and_line_targets'),
    ]

    operations = [
        migrations.CreateModel(
            name='LineGradeTarget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_1_units', models.PositiveIntegerField(default=500, verbose_name='تارگت ۱ (تعداد کالا)')),
                ('target_1_reward', models.PositiveBigIntegerField(default=5000000, verbose_name='پاداش تارگت ۱ (ریال)')),
                ('target_2_units', models.PositiveIntegerField(default=1000, verbose_name='تارگت ۲ (تعداد کالا)')),
                ('target_2_reward', models.PositiveBigIntegerField(default=12000000, verbose_name='پاداش تارگت ۲ (ریال)')),
                ('target_3_units', models.PositiveIntegerField(default=3000, verbose_name='تارگت ۳ (تعداد کالا)')),
                ('target_3_reward', models.PositiveBigIntegerField(default=30000000, verbose_name='پاداش تارگت ۳ (ریال)')),
                ('is_active', models.BooleanField(default=True, verbose_name='فعال')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('commission_level', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='line_targets', to='core.commissionlevel', verbose_name='سطح / گرید')),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grade_targets', to='core.department', verbose_name='لاین / بخش')),
            ],
            options={
                'verbose_name': 'تارگت لاین و گرید',
                'verbose_name_plural': 'تارگت‌های لاین‌ها و گریدها',
                'ordering': ['department__name', 'commission_level__code'],
                'unique_together': {('department', 'commission_level')},
            },
        ),
    ]
