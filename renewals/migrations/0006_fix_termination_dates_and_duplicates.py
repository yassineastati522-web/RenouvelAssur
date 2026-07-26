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


def clean_text(value):
    return str(value or "").strip()


def canonical_policy(contract):
    policy = re.sub(r"\s*/\s*", "/", clean_text(contract.policy_number))
    category = clean_text(contract.category)
    if category and policy and "/" not in policy:
        return f"{category}/{policy}"
    return policy


def contract_fingerprint(contract):
    return (
        canonical_policy(contract),
        normalize(contract.client.name),
        normalize(contract.registration),
        contract.effective_date,
        contract.end_date,
        normalize(contract.event),
        contract.total_premium,
        contract.net_premium,
    )


def fix_termination_dates_and_duplicates(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    CallInteraction = apps.get_model("renewals", "CallInteraction")
    Renewal = apps.get_model("renewals", "Renewal")
    Termination = apps.get_model("renewals", "Termination")

    termination_tokens = ("resili", "annul", "ristourne")
    terminations = Termination.objects.select_related("contract").all()
    for termination in terminations.iterator():
        contract = termination.contract
        event = normalize(contract.event)
        if (
            not contract.manually_terminated
            and contract.effective_date
            and any(token in event for token in termination_tokens)
            and termination.date != contract.effective_date
        ):
            termination.date = contract.effective_date
            termination.save(update_fields=["date"])

    groups = {}
    contracts = Contract.objects.select_related("client").order_by("pk")
    for contract in contracts.iterator():
        groups.setdefault(contract_fingerprint(contract), []).append(contract)

    merge_fields = (
        "agent_reference",
        "agent_code",
        "event",
        "pack_code",
        "brand",
        "registration",
        "net_premium",
        "cash_premium",
        "total_premium",
        "net_payable",
        "effective_date",
        "issue_date",
        "assigned_agent_id",
    )
    status_priority = {
        "to_contact": 0,
        "to_confirm": 1,
        "callback": 2,
        "wants": 3,
        "quote": 4,
        "unreachable": 5,
        "refused": 6,
        "competitor": 7,
        "renewed": 8,
        "terminated": 9,
    }

    for duplicate_group in groups.values():
        if len(duplicate_group) < 2:
            continue

        contract_ids = [contract.pk for contract in duplicate_group]
        is_linked_to_renewal = (
            Renewal.objects.filter(old_contract_id__in=contract_ids).exists()
            or Renewal.objects.filter(new_contract_id__in=contract_ids).exists()
            or Contract.objects.filter(renewed_contract_id__in=contract_ids).exists()
            or any(contract.renewed_contract_id for contract in duplicate_group)
        )
        if is_linked_to_renewal:
            continue

        survivor = max(
            duplicate_group,
            key=lambda contract: (
                "/" in contract.policy_number,
                bool(contract.receipt),
                bool(contract.event),
                contract.total_premium is not None,
                contract.from_upcoming_file,
                -contract.pk,
            ),
        )
        duplicates = [
            contract for contract in duplicate_group if contract.pk != survivor.pk
        ]

        for duplicate in duplicates:
            for field in merge_fields:
                if getattr(survivor, field) in (None, ""):
                    setattr(survivor, field, getattr(duplicate, field))
            survivor.from_upcoming_file = (
                survivor.from_upcoming_file or duplicate.from_upcoming_file
            )
            survivor.manually_terminated = (
                survivor.manually_terminated or duplicate.manually_terminated
            )
            if status_priority.get(duplicate.renewal_status, 0) > status_priority.get(
                survivor.renewal_status, 0
            ):
                survivor.renewal_status = duplicate.renewal_status

        canonical = canonical_policy(survivor)
        if (
            canonical != survivor.policy_number
            and not Contract.objects.filter(
                policy_number=canonical,
                receipt=survivor.receipt,
            ).exclude(pk=survivor.pk).exists()
        ):
            survivor.policy_number = canonical

        survivor.save(
            update_fields=[
                "policy_number",
                *merge_fields,
                "from_upcoming_file",
                "manually_terminated",
                "renewal_status",
            ]
        )

        survivor_termination = Termination.objects.filter(
            contract_id=survivor.pk
        ).first()
        for duplicate in duplicates:
            CallInteraction.objects.filter(contract_id=duplicate.pk).update(
                contract_id=survivor.pk
            )
            duplicate_termination = Termination.objects.filter(
                contract_id=duplicate.pk
            ).first()
            if duplicate_termination:
                if survivor_termination:
                    duplicate_termination.delete()
                else:
                    duplicate_termination.contract_id = survivor.pk
                    duplicate_termination.save(update_fields=["contract"])
                    survivor_termination = duplicate_termination
            duplicate.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0005_import_type_and_upcoming_source"),
    ]

    operations = [
        migrations.RunPython(
            fix_termination_dates_and_duplicates,
            migrations.RunPython.noop,
        ),
    ]
