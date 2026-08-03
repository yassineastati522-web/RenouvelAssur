import re
import unicodedata

from django.db import migrations


def normalize(value):
    value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    return re.sub(r"[^a-z0-9]+", "", value)


def canonical_policy(contract):
    policy = re.sub(r"\s*/\s*", "/", str(contract.policy_number or "").strip())
    category = str(contract.category or "").strip()
    if category and policy and "/" not in policy:
        return f"{category}/{policy}"
    return policy


def same_subject(source, candidate):
    if canonical_policy(source) != canonical_policy(candidate):
        return False
    source_vehicle = normalize(source.registration)
    candidate_vehicle = normalize(candidate.registration)
    if source_vehicle and candidate_vehicle and source_vehicle != candidate_vehicle:
        return False
    return bool(
        source.client_id == candidate.client_id
        or normalize(source.client.name) == normalize(candidate.client.name)
    )


def covers_termination(candidate, stopped_on):
    if candidate.effective_date and stopped_on <= candidate.effective_date:
        return False
    return stopped_on <= candidate.end_date


def repair_post_import_terminations(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    CallInteraction = apps.get_model("renewals", "CallInteraction")
    Renewal = apps.get_model("renewals", "Renewal")
    Termination = apps.get_model("renewals", "Termination")

    contracts = list(Contract.objects.select_related("client").order_by("pk"))
    terminations = {
        termination.contract_id: termination
        for termination in Termination.objects.all()
    }

    # Une ligne de résiliation restée isolée porte encore la PRIME_TOTAL
    # négative exacte sur son Contract. C'est la seule récupération fiable.
    for contract in contracts:
        termination = terminations.get(contract.pk)
        if (
            termination is not None
            and contract.total_premium is not None
            and contract.total_premium < 0
        ):
            termination.premium = contract.total_premium
            termination.save(update_fields=["premium"])

    removed_ids = set()
    negative_sources = [
        contract
        for contract in contracts
        if contract.pk in terminations
        and contract.total_premium is not None
        and contract.total_premium < 0
    ]
    for source in negative_sources:
        source_id = source.pk
        if source_id in removed_ids:
            continue
        source_termination = terminations[source_id]
        candidates = [
            candidate
            for candidate in contracts
            if candidate.pk != source_id
            and candidate.pk not in removed_ids
            and (candidate.total_premium is None or candidate.total_premium >= 0)
            and same_subject(source, candidate)
            and covers_termination(candidate, source_termination.date)
        ]
        if not candidates:
            continue
        survivor = min(
            candidates,
            key=lambda candidate: (
                candidate.renewal_status == "terminated",
                (candidate.end_date - source_termination.date).days,
                candidate.pk,
            ),
        )

        survivor_termination = terminations.get(survivor.pk)
        if survivor_termination is None:
            source_termination.contract_id = survivor.pk
            source_termination.save(update_fields=["contract"])
            survivor_termination = source_termination
        else:
            if source_termination.date < survivor_termination.date:
                survivor_termination.date = source_termination.date
                survivor_termination.reason = (
                    source_termination.reason or survivor_termination.reason
                )
                survivor_termination.premium = source_termination.premium
            elif (
                source_termination.date == survivor_termination.date
                and survivor_termination.premium is None
            ):
                survivor_termination.premium = source_termination.premium
            if (
                survivor_termination.legacy_net_payable is None
                and source_termination.legacy_net_payable is not None
            ):
                survivor_termination.legacy_net_payable = (
                    source_termination.legacy_net_payable
                )
            survivor_termination.save(
                update_fields=[
                    "date",
                    "reason",
                    "premium",
                    "legacy_net_payable",
                ]
            )
            source_termination.delete()

        survivor.end_date = survivor_termination.date
        survivor.event = survivor_termination.reason or source.event or "Résiliation"
        survivor.renewal_status = "terminated"
        survivor.renewed_contract_id = None
        survivor.save(
            update_fields=[
                "end_date",
                "event",
                "renewal_status",
                "renewed_contract",
            ]
        )

        CallInteraction.objects.filter(contract_id=source_id).update(
            contract_id=survivor.pk
        )
        Contract.objects.filter(renewed_contract_id=source_id).update(
            renewed_contract_id=None
        )
        Renewal.objects.filter(new_contract_id=source_id).update(
            new_contract_id=survivor.pk
        )
        survivor_renewal = Renewal.objects.filter(
            old_contract_id=survivor.pk
        ).first()
        source_renewal = Renewal.objects.filter(old_contract_id=source_id).first()
        if source_renewal:
            if survivor_renewal:
                source_renewal.delete()
            else:
                source_renewal.old_contract_id = survivor.pk
                source_renewal.save(update_fields=["old_contract"])

        source.delete()
        removed_ids.add(source_id)
        terminations.pop(source_id, None)
        terminations[survivor.pk] = survivor_termination


class Migration(migrations.Migration):
    dependencies = [("renewals", "0016_restore_termination_premium_schema")]

    operations = [
        migrations.RunPython(
            repair_post_import_terminations,
            migrations.RunPython.noop,
        )
    ]
