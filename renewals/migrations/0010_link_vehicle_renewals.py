import re
import unicodedata
from datetime import timedelta

from django.db import migrations


def normalized_registration(value):
    value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    return re.sub(r"[^a-z0-9]+", "", value)


def link_vehicle_renewals(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    contracts = list(
        Contract.objects.exclude(registration="").only(
            "pk",
            "registration",
            "effective_date",
            "issue_date",
            "end_date",
            "renewal_status",
            "renewed_contract_id",
            "manually_terminated",
        )
    )
    groups = {}
    for contract in contracts:
        registration = normalized_registration(contract.registration)
        if registration:
            groups.setdefault(registration, []).append(contract)

    claimed_successors = {
        contract.renewed_contract_id: contract.pk
        for contract in contracts
        if contract.renewed_contract_id
    }
    changed = []
    for vehicle_contracts in groups.values():
        for old_contract in sorted(
            vehicle_contracts,
            key=lambda contract: (contract.end_date, contract.pk),
        ):
            if (
                old_contract.manually_terminated
                or old_contract.renewal_status == "terminated"
            ):
                continue
            earliest_start = old_contract.end_date - timedelta(days=1)
            successors = []
            for candidate in vehicle_contracts:
                candidate_start = candidate.effective_date or candidate.issue_date
                if (
                    candidate.pk != old_contract.pk
                    and candidate_start
                    and candidate_start >= earliest_start
                    and candidate.end_date > old_contract.end_date
                    and not candidate.manually_terminated
                    and candidate.renewal_status != "terminated"
                    and claimed_successors.get(candidate.pk)
                    in (None, old_contract.pk)
                ):
                    successors.append(
                        (candidate_start, candidate.end_date, candidate.pk, candidate)
                    )
            if not successors:
                continue
            successor = min(successors, key=lambda item: item[:3])[3]
            if (
                old_contract.renewed_contract_id != successor.pk
                or old_contract.renewal_status != "renewed"
            ):
                if (
                    old_contract.renewed_contract_id
                    and claimed_successors.get(old_contract.renewed_contract_id)
                    == old_contract.pk
                ):
                    claimed_successors.pop(old_contract.renewed_contract_id)
                old_contract.renewed_contract_id = successor.pk
                old_contract.renewal_status = "renewed"
                claimed_successors[successor.pk] = old_contract.pk
                changed.append(old_contract)

    if changed:
        Contract.objects.bulk_update(
            changed,
            ["renewed_contract", "renewal_status"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0009_contract_provisional_selected_count"),
    ]

    operations = [
        migrations.RunPython(
            link_vehicle_renewals,
            migrations.RunPython.noop,
        ),
    ]
