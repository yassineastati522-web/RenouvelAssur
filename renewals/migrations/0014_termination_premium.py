from django.db import migrations, models


def preserve_existing_negative_termination_premiums(apps, schema_editor):
    Termination = apps.get_model("renewals", "Termination")
    changed = []
    for termination in Termination.objects.select_related("contract"):
        contract_premium = termination.contract.total_premium
        if contract_premium is None or contract_premium >= 0:
            continue
        termination.premium = contract_premium
        changed.append(termination)
    if changed:
        Termination.objects.bulk_update(
            changed,
            ["premium"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("renewals", "0013_consolidate_terminations")]

    operations = [
        migrations.AddField(
            model_name="termination",
            name="premium",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=14,
                null=True,
                verbose_name="prime de résiliation",
            ),
        ),
        migrations.RunPython(
            preserve_existing_negative_termination_premiums,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="termination",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(premium__isnull=True)
                    | models.Q(premium__lt=0)
                ),
                name="termination_premium_negative_or_null",
            ),
        ),
    ]
