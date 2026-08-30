import datetime
from decimal import Decimal
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


def seed_default_shifts(apps, schema_editor):
    Shift = apps.get_model("core", "Shift")
    Employee = apps.get_model("core", "Employee")

    morning, _ = Shift.objects.get_or_create(
        code="MORNING",
        defaults={
            "title": "شیفت صبح",
            "start_time": datetime.time(10, 0),
            "end_time": datetime.time(16, 0),
            "standard_hours": Decimal("6.0"),
            "is_active": True,
            "sort_order": 1,
        }
    )

    evening, _ = Shift.objects.get_or_create(
        code="EVENING",
        defaults={
            "title": "شیفت عصر",
            "start_time": datetime.time(16, 0),
            "end_time": datetime.time(22, 0),
            "standard_hours": Decimal("6.0"),
            "is_active": True,
            "sort_order": 2,
        }
    )

    Employee.objects.filter(default_shift__isnull=True).update(default_shift=morning)


def reverse_default_shifts(apps, schema_editor):
    Shift = apps.get_model("core", "Shift")
    Shift.objects.filter(code__in=["MORNING", "EVENING"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_activity_duration_minutes_activity_end_time_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Shift',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=20, unique=True, verbose_name='کد شیفت')),
                ('title', models.CharField(max_length=100, verbose_name='عنوان شیفت')),
                ('start_time', models.TimeField(verbose_name='ساعت شروع')),
                ('end_time', models.TimeField(verbose_name='ساعت پایان')),
                ('standard_hours', models.DecimalField(decimal_places=1, default=Decimal('6.0'), max_digits=4, validators=[django.core.validators.MinValueValidator(Decimal('0.5')), django.core.validators.MaxValueValidator(Decimal('24.0'))], verbose_name='ساعت کاری استاندارد')),
                ('is_active', models.BooleanField(default=True, verbose_name='فعال')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='ترتیب')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'شیفت',
                'verbose_name_plural': 'شیفت\u200cها',
                'ordering': ['sort_order', 'start_time', 'title'],
            },
        ),
        migrations.AddField(
            model_name='employee',
            name='default_shift',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='employees', to='core.shift', verbose_name='شیفت پیش\u200cفرض'),
        ),
        migrations.AddField(
            model_name='employee',
            name='standard_daily_hours',
            field=models.DecimalField(decimal_places=1, default=Decimal('6.0'), max_digits=4, validators=[django.core.validators.MinValueValidator(Decimal('1.0')), django.core.validators.MaxValueValidator(Decimal('24.0'))], verbose_name='ساعت کاری روزانه'),
        ),
        migrations.RunPython(
            seed_default_shifts,
            reverse_default_shifts,
        ),
    ]
