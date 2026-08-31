from django.db import migrations, models
import django.db.models.deletion


def create_default_line_targets(apps, schema_editor):
    Department = apps.get_model("core", "Department")
    LineTarget = apps.get_model("core", "LineTarget")
    for dept in Department.objects.all():
        LineTarget.objects.get_or_create(
            department=dept,
            defaults={
                "bronze_units": 500,
                "bronze_reward": 5000000,
                "silver_units": 1000,
                "silver_reward": 12000000,
                "gold_units": 3000,
                "gold_reward": 30000000,
                "is_active": True,
            }
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_linegradetarget'),
    ]

    operations = [
        migrations.CreateModel(
            name='LineTarget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bronze_units', models.PositiveIntegerField(default=500, verbose_name='تارگت برنزی (تعداد کالا)')),
                ('bronze_reward', models.PositiveBigIntegerField(default=5000000, verbose_name='پاداش تارگت برنزی (ریال)')),
                ('silver_units', models.PositiveIntegerField(default=1000, verbose_name='تارگت نقره‌ای (تعداد کالا)')),
                ('silver_reward', models.PositiveBigIntegerField(default=12000000, verbose_name='پاداش تارگت نقره‌ای (ریال)')),
                ('gold_units', models.PositiveIntegerField(default=3000, verbose_name='تارگت طلایی (تعداد کالا)')),
                ('gold_reward', models.PositiveBigIntegerField(default=30000000, verbose_name='پاداش تارگت طلایی (ریال)')),
                ('is_active', models.BooleanField(default=True, verbose_name='فعال')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('department', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='target_settings', to='core.department', verbose_name='لاین / بخش')),
            ],
            options={
                'verbose_name': 'تارگت لاین',
                'verbose_name_plural': 'تارگت‌های لاین‌ها',
                'ordering': ['department__name'],
            },
        ),
        migrations.RunPython(
            create_default_line_targets,
            migrations.RunPython.noop,
        ),
    ]
