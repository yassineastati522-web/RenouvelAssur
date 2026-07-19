from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0003_remove_pdf_preview_and_update_call_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="brand",
            field=models.CharField(blank=True, db_index=True, max_length=100, verbose_name="marque"),
        ),
    ]
