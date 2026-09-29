from django.db import migrations, models


def globalize_activities(apps, schema_editor):
    LineActivityType = apps.get_model("core", "LineActivityType")
    ShiftLogActivityEntry = apps.get_model("core", "ShiftLogActivityEntry")
    kept = {}
    for activity in LineActivityType.objects.order_by("pk"):
        title = (activity.title or "").strip()
        if title in kept:
            ShiftLogActivityEntry.objects.filter(activity_type=activity).update(activity_type_id=kept[title])
            activity.delete()
        else:
            if activity.title != title:
                activity.title = title
                activity.save(update_fields=["title"])
            kept[title] = activity.pk


class Migration(migrations.Migration):
    # ادغام ردیف‌ها تریگر کلید خارجی را باز می‌گذارد؛ ALTER در همان تراکنش
    # روی PostgreSQL با خطای pending trigger events شکست می‌خورد.
    atomic = False

    dependencies = [
        ("core", "0025_line_activity_count_method"),
    ]

    operations = [
        migrations.RunPython(globalize_activities, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="lineactivitytype",
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name="lineactivitytype",
            name="department",
        ),
        migrations.AlterField(
            model_name="lineactivitytype",
            name="title",
            field=models.CharField(max_length=120, unique=True, verbose_name="نام فعالیت"),
        ),
        migrations.AlterModelOptions(
            name="lineactivitytype",
            options={
                "ordering": ["sort_order", "title", "pk"],
                "verbose_name": "فعالیت",
                "verbose_name_plural": "فعالیت‌ها",
            },
        ),
    ]
