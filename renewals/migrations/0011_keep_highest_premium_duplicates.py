import re
import unicodedata
from decimal import Decimal

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
    policy = re.sub(
        r"\s*/\s*",
        "/",
        str(contract.policy_number or "").strip(),
    )
    category = str(contract.category or "").strip()
    if category and policy and "/" not in policy:
        return f"{category}/{policy}"
    return policy


def business_identity(contract):
    policy = canonical_policy(contract)
    client_name = normalize(contract.client.name)
    registration = normalize(contract.registration)
    if not policy or not client_name or not registration:
        return None
    return (
        policy,
        client_name,
        registration,
        contract.effective_date,
        contract.end_date,
    )


def premium_rank(contract):
    if contract.total_premium is None:
        return Decimal("-Infinity")
    return contract.total_premium


def keep_highest_premium_duplicates(apps, schema_editor):
    Contract = apps.get_model("renewals", "Contract")
    CallInteraction = apps.get_model("renewals", "CallInteraction")
    Renewal = apps.get_model("renewals", "Renewal")
    Termination = apps.get_model("renewals", "Termination")

    groups = {}
    for contract in (
        Contract.objects.select_related("client").order_by("pk").iterator()
    ):
        identity = business_identity(contract)
        if identity is not None:
            groups.setdefault(identity, []).append(contract)

    fill_if_empty_fields = (
        "category",
        "agent_reference",
        "agent_code",
        "event",
        "pack_code",
        "brand",
        "net_premium",
        "cash_premium",
        "net_payable",
        "issue_date",
        "assigned_agent_id",
        "provisional_attestation",
        "provisional_due_date",
        "provisional_status",
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

    for group in groups.values():
        if len(group) < 2:
            continue

        survivor = max(
            group,
            key=lambda contract: (
                premium_rank(contract),
                bool(contract.receipt),
                bool(contract.event),
                bool(contract.assigned_agent_id),
                contract.from_upcoming_file,
                -contract.pk,
            ),
        )
        duplicates = [
            contract for contract in group if contract.pk != survivor.pk
        ]
        duplicate_ids = [contract.pk for contract in duplicates]
        group_ids = {contract.pk for contract in group}

        desired_renewed_contract_id = survivor.renewed_contract_id
        if desired_renewed_contract_id in group_ids:
            desired_renewed_contract_id = None
        if desired_renewed_contract_id is None:
            desired_renewed_contract_id = next(
                (
                    contract.renewed_contract_id
                    for contract in duplicates
                    if contract.renewed_contract_id
                    and contract.renewed_contract_id not in group_ids
                ),
                None,
            )

        for duplicate in duplicates:
            for field in fill_if_empty_fields:
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
            if status_priority.get(
                duplicate.renewal_status,
                0,
            ) > status_priority.get(survivor.renewal_status, 0):
                survivor.renewal_status = duplicate.renewal_status

        Contract.objects.filter(pk__in=duplicate_ids).update(
            renewed_contract_id=None,
        )
        survivor.renewed_contract_id = desired_renewed_contract_id
        survivor.save(
            update_fields=[
                *fill_if_empty_fields,
                "from_upcoming_file",
                "manually_terminated",
                "is_provisional",
                "provisional_delivered_count",
                "provisional_allowed_count",
                "provisional_selected_count",
                "renewal_status",
                "renewed_contract",
            ]
        )

        external_predecessors = list(
            Contract.objects.filter(
                renewed_contract_id__in=duplicate_ids,
            )
            .exclude(pk__in=group_ids)
            .order_by("pk")
        )
        survivor_already_claimed = (
            Contract.objects.filter(renewed_contract_id=survivor.pk)
            .exclude(pk__in=group_ids)
            .exists()
        )
        if external_predecessors and not survivor_already_claimed:
            predecessor = external_predecessors[0]
            predecessor.renewed_contract_id = survivor.pk
            predecessor.save(update_fields=["renewed_contract"])

        survivor_renewal = Renewal.objects.filter(
            old_contract_id=survivor.pk,
        ).first()
        for duplicate in duplicates:
            duplicate_renewal = Renewal.objects.filter(
                old_contract_id=duplicate.pk,
            ).first()
            if duplicate_renewal:
                if survivor_renewal:
                    duplicate_renewal.delete()
                else:
                    duplicate_renewal.old_contract_id = survivor.pk
                    duplicate_renewal.save(update_fields=["old_contract"])
                    survivor_renewal = duplicate_renewal
        Renewal.objects.filter(new_contract_id__in=duplicate_ids).update(
            new_contract_id=survivor.pk,
        )

        survivor_termination = Termination.objects.filter(
            contract_id=survivor.pk,
        ).first()
        for duplicate in duplicates:
            CallInteraction.objects.filter(contract_id=duplicate.pk).update(
                contract_id=survivor.pk,
            )
            duplicate_termination = Termination.objects.filter(
                contract_id=duplicate.pk,
            ).first()
            if duplicate_termination:
                if survivor_termination:
                    if (
                        duplicate_termination.date
                        < survivor_termination.date
                    ):
                        survivor_termination.date = (
                            duplicate_termination.date
                        )
                    if (
                        not survivor_termination.reason
                        and duplicate_termination.reason
                    ):
                        survivor_termination.reason = (
                            duplicate_termination.reason
                        )
                    survivor_termination.save(
                        update_fields=["date", "reason"],
                    )
                    duplicate_termination.delete()
                else:
                    duplicate_termination.contract_id = survivor.pk
                    duplicate_termination.save(update_fields=["contract"])
                    survivor_termination = duplicate_termination
            duplicate.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("renewals", "0010_link_vehicle_renewals"),
    ]

    operations = [
        migrations.RunPython(
            keep_highest_premium_duplicates,
            migrations.RunPython.noop,
        ),
    ]
