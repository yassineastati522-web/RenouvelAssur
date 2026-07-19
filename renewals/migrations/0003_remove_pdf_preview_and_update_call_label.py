from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0002_importpreview"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ImportPreview",
        ),
        migrations.AlterField(
            model_name="callinteraction",
            name="call_result",
            field=models.CharField(
                choices=[
                    ("not_called", "Pas encore appelé"),
                    ("answered", "Client appelé"),
                    ("voicemail", "Boîte vocale"),
                    ("unreachable", "Non joignable"),
                    ("off", "Téléphone éteint"),
                    ("wrong", "Numéro incorrect"),
                    ("busy", "Occupé"),
                    ("callback", "Rappel demandé"),
                ],
                max_length=20,
            ),
        ),
    ]
