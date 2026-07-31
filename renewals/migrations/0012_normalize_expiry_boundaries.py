from datetime import timedelta

from django.db import migrations, models


def normalize_expiry_boundaries(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    # Les contrats enrichis par le fichier d'échéances contiennent déjà le
    # dernier jour couvert. Les autres contrats issus d'un bordereau portent
    # une borne exclusive à minuit et doivent être ramenés au jour précédent.
    candidates = Contract.objects.filter(from_upcoming_file=False).filter(
        models.Q(is_provisional=True)
        | ~models.Q(event="")
        | ~models.Q(receipt="")
        | models.Q(total_premium__isnull=False)
        | models.Q(net_premium__isnull=False)
    )
    changed = []
    for contract in candidates.iterator(chunk_size=500):
        contract.end_date -= timedelta(days=1)
        changed.append(contract)
    if changed:
        Contract.objects.bulk_update(changed, ["end_date"], batch_size=500)


def restore_expiry_boundaries(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    candidates = Contract.objects.filter(from_upcoming_file=False).filter(
        models.Q(is_provisional=True)
        | ~models.Q(event="")
        | ~models.Q(receipt="")
        | models.Q(total_premium__isnull=False)
        | models.Q(net_premium__isnull=False)
    )
    changed = []
    for contract in candidates.iterator(chunk_size=500):
        contract.end_date += timedelta(days=1)
        changed.append(contract)
    if changed:
        Contract.objects.bulk_update(changed, ["end_date"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("renewals", "0011_keep_highest_premium_duplicates")]

    operations = [
        migrations.RunPython(
            normalize_expiry_boundaries,
            restore_expiry_boundaries,
        ),
    ]
