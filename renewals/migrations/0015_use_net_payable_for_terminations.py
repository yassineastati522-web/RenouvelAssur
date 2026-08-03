from django.db import migrations, models


def replace_total_premium_with_net_payable(apps, schema_editor):
    Termination = apps.get_model("renewals", "Termination")
    changed = []
    for termination in Termination.objects.select_related("contract"):
        contract_net_payable = termination.contract.net_payable
        exact_value = (
            contract_net_payable
            if contract_net_payable is not None and contract_net_payable < 0
            else None
        )
        if termination.net_payable == exact_value:
            continue
        termination.net_payable = exact_value
        changed.append(termination)
    if changed:
        Termination.objects.bulk_update(
            changed,
            ["net_payable"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("renewals", "0014_termination_premium")]

    operations = [
        migrations.RemoveConstraint(
            model_name="termination",
            name="termination_premium_negative_or_null",
        ),
        migrations.RenameField(
            model_name="termination",
            old_name="premium",
            new_name="net_payable",
        ),
        migrations.AlterField(
            model_name="termination",
            name="net_payable",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=14,
                null=True,
                verbose_name="net à payer de la résiliation",
            ),
        ),
        migrations.RunPython(
            replace_total_premium_with_net_payable,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="termination",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(net_payable__isnull=True)
                    | models.Q(net_payable__lt=0)
                ),
                name="termination_net_payable_negative_or_null",
            ),
        ),
    ]
