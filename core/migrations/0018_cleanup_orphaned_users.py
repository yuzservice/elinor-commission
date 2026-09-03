from django.db import migrations


def cleanup_orphaned_users(apps, schema_editor):
    User = apps.get_model("auth", "User")
    # پاکسازی حساب‌های کاربری که پرونده کارمندی ندارند و سوپریوزر نیستند
    orphaned_users = User.objects.filter(employee__isnull=True, is_superuser=False)
    orphaned_users.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_drop_legacy_activity_tables"),
    ]

    operations = [
        migrations.RunPython(cleanup_orphaned_users, migrations.RunPython.noop),
    ]
