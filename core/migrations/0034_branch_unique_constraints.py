from django.db import migrations, models


CONSTRAINTS = (
    ("unique_level_code_per_branch", "core_commissionlevel", "branch_id, code", "commissionlevel", ("branch", "code")),
    ("unique_department_name_per_branch", "core_department", "branch_id, name", "department", ("branch", "name")),
    ("unique_activity_title_per_branch", "core_lineactivitytype", "branch_id, title", "lineactivitytype", ("branch", "title")),
    ("unique_shift_code_per_branch", "core_shift", "branch_id, code", "shift", ("branch", "code")),
    ("unique_violation_code_per_branch", "core_violationrule", "branch_id, code", "violationrule", ("branch", "code")),
)


def add_branch_uniques(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for name, table, columns, _model, _fields in CONSTRAINTS:
            cursor.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", [name])
            if cursor.fetchone():
                continue
            cursor.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({columns})")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0033_admin_without_commission"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name=model,
                    constraint=models.UniqueConstraint(fields=fields, name=name),
                )
                for name, _table, _columns, model, fields in CONSTRAINTS
            ],
            database_operations=[
                migrations.RunPython(add_branch_uniques, migrations.RunPython.noop),
            ],
        ),
    ]
