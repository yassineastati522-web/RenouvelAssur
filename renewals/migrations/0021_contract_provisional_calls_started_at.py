from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0020_alter_auditevent_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="provisional_calls_started_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="début des appels de la provisoire courante",
            ),
        ),
    ]
