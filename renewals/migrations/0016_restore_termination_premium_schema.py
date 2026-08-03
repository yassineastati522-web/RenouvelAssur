from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("renewals", "0015_use_net_payable_for_terminations")]

    operations = [
        migrations.RemoveConstraint(
            model_name="termination",
            name="termination_net_payable_negative_or_null",
        ),
        migrations.RenameField(
            model_name="termination",
            old_name="net_payable",
            new_name="legacy_net_payable",
        ),
        migrations.AlterField(
            model_name="termination",
            name="legacy_net_payable",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                editable=False,
                max_digits=14,
                null=True,
                verbose_name="ancienne valeur NET_A_PAYE (audit)",
            ),
        ),
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
        migrations.AddConstraint(
            model_name="termination",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(legacy_net_payable__isnull=True)
                    | models.Q(legacy_net_payable__lt=0)
                ),
                name="termination_legacy_net_negative_or_null",
            ),
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
