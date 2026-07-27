from django.db import migrations


def clear_contracts_and_imports(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    ImportBatch = apps.get_model("renewals", "ImportBatch")

    Contract.objects.all().delete()
    ImportBatch.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0006_fix_termination_dates_and_duplicates"),
    ]

    operations = [
        migrations.RunPython(
            clear_contracts_and_imports,
            migrations.RunPython.noop,
        ),
    ]
