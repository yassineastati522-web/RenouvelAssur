from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0021_contract_provisional_calls_started_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="renewal_calls_started_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="début des appels de renouvellement après provisoire",
            ),
        ),
    ]
