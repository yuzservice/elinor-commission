from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_branches_and_admin_scope"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employee",
            name="commission_level",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="employees",
                to="core.commissionlevel",
                verbose_name="گرید پورسانت",
            ),
        ),
        migrations.AlterField(
            model_name="employee",
            name="mobile",
            field=models.CharField(
                blank=True,
                max_length=11,
                null=True,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        "^09\\d{9}$",
                        "شماره موبایل باید ۱۱ رقم و با 09 شروع شود.",
                    )
                ],
                verbose_name="شماره موبایل",
            ),
        ),
    ]
