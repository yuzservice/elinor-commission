from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_branch_unique_constraints'),
    ]

    operations = [
        migrations.AlterField(
            model_name='dailyshiftlog',
            name='frozen_commission_amount',
            field=models.PositiveBigIntegerField(default=0, verbose_name='مبلغ پورسانت فریز شده (تومان)'),
        ),
        migrations.AlterField(
            model_name='departmentmonthlytarget',
            name='reward_amount',
            field=models.PositiveBigIntegerField(blank=True, default=0, verbose_name='پاداش دستیابی به تارگت لاین (تومان)'),
        ),
        migrations.AlterField(
            model_name='departmentmonthlytarget',
            name='target_commission_points',
            field=models.PositiveBigIntegerField(blank=True, default=0, verbose_name='تارگت پورسانت ناخالص لاین (تومان)'),
        ),
        migrations.AlterField(
            model_name='departmentmonthlytarget',
            name='target_sales_amount',
            field=models.PositiveBigIntegerField(blank=True, default=0, verbose_name='تارگت مبلغ فروش لاین (تومان)'),
        ),
        migrations.AlterField(
            model_name='linecommissionrate',
            name='rate_per_unit',
            field=models.PositiveIntegerField(default=1000, verbose_name='مبلغ پورسانت به ازای هر کالا (تومان)'),
        ),
        migrations.AlterField(
            model_name='linegradetarget',
            name='target_1_reward',
            field=models.PositiveBigIntegerField(default=5000000, verbose_name='پاداش تارگت ۱ (تومان)'),
        ),
        migrations.AlterField(
            model_name='linegradetarget',
            name='target_2_reward',
            field=models.PositiveBigIntegerField(default=12000000, verbose_name='پاداش تارگت ۲ (تومان)'),
        ),
        migrations.AlterField(
            model_name='linegradetarget',
            name='target_3_reward',
            field=models.PositiveBigIntegerField(default=30000000, verbose_name='پاداش تارگت ۳ (تومان)'),
        ),
        migrations.AlterField(
            model_name='lineshiftperformance',
            name='sales_amount',
            field=models.PositiveBigIntegerField(blank=True, default=0, verbose_name='مبلغ فروش (تومان)'),
        ),
        migrations.AlterField(
            model_name='linetarget',
            name='bronze_reward',
            field=models.PositiveBigIntegerField(default=5000000, verbose_name='پاداش تارگت برنزی (تومان)'),
        ),
        migrations.AlterField(
            model_name='linetarget',
            name='gold_reward',
            field=models.PositiveBigIntegerField(default=30000000, verbose_name='پاداش تارگت طلایی (تومان)'),
        ),
        migrations.AlterField(
            model_name='linetarget',
            name='silver_reward',
            field=models.PositiveBigIntegerField(default=12000000, verbose_name='پاداش تارگت نقره‌ای (تومان)'),
        ),
    ]
