from django.db import migrations, models
import django.db.models.deletion


def seed_default_line_rates(apps, schema_editor):
    Department = apps.get_model("core", "Department")
    CommissionLevel = apps.get_model("core", "CommissionLevel")
    LineCommissionRate = apps.get_model("core", "LineCommissionRate")

    levels = list(CommissionLevel.objects.all())
    departments = list(Department.objects.all())

    for dept in departments:
        for lvl in levels:
            LineCommissionRate.objects.get_or_create(
                department=dept,
                commission_level=lvl,
                defaults={
                    "rate_per_unit": lvl.performance_rate or 1000,
                    "is_active": True,
                }
            )


def reverse_default_line_rates(apps, schema_editor):
    LineCommissionRate = apps.get_model("core", "LineCommissionRate")
    LineCommissionRate.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_lineshiftperformance'),
    ]

    operations = [
        migrations.CreateModel(
            name='LineCommissionRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rate_per_unit', models.PositiveIntegerField(default=1000, verbose_name='مبلغ پورسانت به ازای هر کالا')),
                ('is_active', models.BooleanField(default=True, verbose_name='فعال')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('commission_level', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='line_rates', to='core.commissionlevel', verbose_name='سطح / گرید')),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='commission_rates', to='core.department', verbose_name='لاین / بخش')),
            ],
            options={
                'verbose_name': 'نرخ پورسانت لاین و گرید',
                'verbose_name_plural': 'نرخ‌های پورسانت لاین‌ها و گریدها',
                'ordering': ['department__name', 'commission_level__code'],
                'unique_together': {('department', 'commission_level')},
            },
        ),
        migrations.RunPython(
            seed_default_line_rates,
            reverse_default_line_rates,
        ),
    ]
