from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0004_contract_brand"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="from_upcoming_file",
            field=models.BooleanField(
                default=False,
                verbose_name="présent dans un fichier d’échéances",
            ),
        ),
        migrations.AddField(
            model_name="importbatch",
            name="import_type",
            field=models.CharField(
                choices=[
                    ("upcoming", "Échéances à venir"),
                    ("bordereau", "Bordereau de production"),
                    ("contacts", "Mise à jour des contacts"),
                    ("general", "Fichier Excel standard"),
                ],
                default="general",
                max_length=20,
                verbose_name="type d’import",
            ),
        ),
    ]
