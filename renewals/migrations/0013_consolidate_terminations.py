import re
import unicodedata
from decimal import Decimal

from django.db import migrations


TERMINATION_TOKENS = ("resili", "annul", "ristourne")


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


def subject_key(contract):
    return (
        canonical_policy(contract),
        normalize(contract.client.name),
        normalize(contract.registration),
    )


def has_termination_event(contract):
    event = normalize(contract.event)
    return bool(event) and any(token in event for token in TERMINATION_TOKENS)


def is_closed(contract, terminations):
    return bool(
        contract.pk in terminations
        or contract.manually_terminated
        or contract.renewal_status == "terminated"
        or has_termination_event(contract)
    )


def cancellation_date(contract, termination=None):
    if termination is not None:
        return termination.date
    if has_termination_event(contract) and contract.effective_date:
        return contract.effective_date
    if contract.manually_terminated or contract.renewal_status == "terminated":
        return contract.end_date
    return contract.effective_date or contract.issue_date or contract.end_date


def relates_to_cycle(source, candidate, stopped_on):
    return bool(
        stopped_on
        and stopped_on <= candidate.end_date
        and (
            not candidate.effective_date
            or stopped_on > candidate.effective_date
        )
    )


def survivor_rank(contract):
    premium = contract.total_premium
    positive_premium = premium is not None and premium > 0
    completeness = sum(
        bool(getattr(contract, field))
        for field in (
            "receipt",
            "brand",
            "registration",
            "effective_date",
            "issue_date",
            "assigned_agent_id",
        )
    )
    return (
        positive_premium,
        not has_termination_event(contract),
        premium if premium is not None else Decimal("-Infinity"),
        completeness,
        contract.from_upcoming_file,
        -contract.pk,
    )


def repair_terminations(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    CallInteraction = apps.get_model("renewals", "CallInteraction")
    Renewal = apps.get_model("renewals", "Renewal")
    Termination = apps.get_model("renewals", "Termination")

    contracts = list(
        Contract.objects.select_related("client").order_by("pk")
    )
    terminations = {
        termination.contract_id: termination
        for termination in Termination.objects.all()
    }
    groups = {}
    for contract in contracts:
        groups.setdefault(subject_key(contract), []).append(contract)

    fill_if_empty = (
        "category",
        "agent_reference",
        "agent_code",
        "pack_code",
        "brand",
        "registration",
        "effective_date",
        "issue_date",
        "assigned_agent_id",
    )

    for group_contracts in groups.values():
        closed_sources = [
            contract
            for contract in group_contracts
            if is_closed(contract, terminations)
        ]
        processed_ids = set()
        for source in sorted(
            closed_sources,
            key=lambda contract: (
                cancellation_date(contract, terminations.get(contract.pk)),
                contract.pk,
            ),
        ):
            if source.pk in processed_ids:
                continue
            source_stop = cancellation_date(
                source,
                terminations.get(source.pk),
            )
            available = [
                contract
                for contract in group_contracts
                if contract.pk not in processed_ids
            ]
            exact_expiry = [
                contract
                for contract in available
                if contract.pk != source.pk
                if abs((contract.end_date - source.end_date).days) <= 1
            ]
            if exact_expiry:
                related = [source, *exact_expiry]
            else:
                related = [
                    contract
                    for contract in available
                    if contract.pk == source.pk
                    or relates_to_cycle(source, contract, source_stop)
                ]
            if source not in related:
                related.append(source)

            related_closed = [
                contract
                for contract in related
                if is_closed(contract, terminations)
            ]
            stopped_on = min(
                cancellation_date(
                    contract,
                    terminations.get(contract.pk),
                )
                for contract in related_closed
            )
            reason_source = min(
                related_closed,
                key=lambda contract: (
                    cancellation_date(
                        contract,
                        terminations.get(contract.pk),
                    ),
                    contract.pk,
                ),
            )
            reason = reason_source.event or "Résiliation"
            survivor = max(related, key=survivor_rank)
            duplicates = [
                contract for contract in related if contract.pk != survivor.pk
            ]
            duplicate_ids = [contract.pk for contract in duplicates]

            for duplicate in duplicates:
                for field in fill_if_empty:
                    if getattr(survivor, field) in (None, ""):
                        setattr(survivor, field, getattr(duplicate, field))
                survivor.from_upcoming_file = (
                    survivor.from_upcoming_file or duplicate.from_upcoming_file
                )
                survivor.manually_terminated = (
                    survivor.manually_terminated or duplicate.manually_terminated
                )
                survivor.is_provisional = (
                    survivor.is_provisional or duplicate.is_provisional
                )
                survivor.provisional_delivered_count = max(
                    survivor.provisional_delivered_count,
                    duplicate.provisional_delivered_count,
                )
                survivor.provisional_allowed_count = max(
                    survivor.provisional_allowed_count,
                    duplicate.provisional_allowed_count,
                )
                survivor.provisional_selected_count = max(
                    survivor.provisional_selected_count,
                    duplicate.provisional_selected_count,
                )

            survivor.event = reason
            survivor.end_date = stopped_on
            survivor.renewal_status = "terminated"
            survivor.renewed_contract_id = None
            survivor.save(
                update_fields=[
                    *fill_if_empty,
                    "event",
                    "end_date",
                    "renewal_status",
                    "renewed_contract",
                    "from_upcoming_file",
                    "manually_terminated",
                    "is_provisional",
                    "provisional_delivered_count",
                    "provisional_allowed_count",
                    "provisional_selected_count",
                ]
            )

            related_terminations = [
                terminations[contract.pk]
                for contract in related
                if contract.pk in terminations
            ]
            survivor_termination = terminations.get(survivor.pk)
            keeper = survivor_termination or (
                min(related_terminations, key=lambda item: item.pk)
                if related_terminations
                else None
            )
            for termination in related_terminations:
                if keeper is not None and termination.pk != keeper.pk:
                    termination.delete()
            if keeper is None:
                keeper = Termination.objects.create(
                    contract_id=survivor.pk,
                    date=stopped_on,
                    reason=reason,
                )
            else:
                keeper.contract_id = survivor.pk
                keeper.date = stopped_on
                keeper.reason = keeper.reason or reason
                keeper.save(update_fields=["contract", "date", "reason"])

            if duplicate_ids:
                CallInteraction.objects.filter(
                    contract_id__in=duplicate_ids
                ).update(contract_id=survivor.pk)
                Contract.objects.filter(
                    renewed_contract_id__in=duplicate_ids
                ).update(renewed_contract_id=None)
                Renewal.objects.filter(
                    new_contract_id__in=duplicate_ids
                ).update(new_contract_id=survivor.pk)
                survivor_renewal = Renewal.objects.filter(
                    old_contract_id=survivor.pk
                ).first()
                for duplicate in duplicates:
                    duplicate_renewal = Renewal.objects.filter(
                        old_contract_id=duplicate.pk
                    ).first()
                    if duplicate_renewal:
                        if survivor_renewal:
                            duplicate_renewal.delete()
                        else:
                            duplicate_renewal.old_contract_id = survivor.pk
                            duplicate_renewal.save(update_fields=["old_contract"])
                            survivor_renewal = duplicate_renewal
                Contract.objects.filter(pk__in=duplicate_ids).delete()

            for contract in related:
                processed_ids.add(contract.pk)
                terminations.pop(contract.pk, None)
            terminations[survivor.pk] = keeper


class Migration(migrations.Migration):
    dependencies = [("renewals", "0012_normalize_expiry_boundaries")]

    operations = [
        migrations.RunPython(
            repair_terminations,
            migrations.RunPython.noop,
        )
    ]
