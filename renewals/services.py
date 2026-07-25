import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zipfile import BadZipFile

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .models import Client, Contract, ImportBatch, Termination


# Les alias sont ordonnés : lorsqu'un fichier contient deux colonnes équivalentes,
# la première valeur non vide est utilisée. Par exemple, IMMATDEF est prioritaire
# sur IMMAPRO dans les bordereaux fournis par l'assureur.
ALIASES = {
    "category": ("cat", "categorie", "type contrat"),
    "policy_number": ("police", "numero police", "n police"),
    "agent_reference": ("reference agent", "ref agent", "libelle intermediaire"),
    "agent_code": ("code agent", "code intermediaire"),
    "event": ("nature evenement", "evenement", "event"),
    "renewed_flag": ("renouvele", "renouvellement", "statut renouvellement"),
    "pack_code": ("code pack convention", "code pack", "convention"),
    "client_name": ("client", "assure", "nom assure", "nom client"),
    "client_phone": ("telephone", "telephone2", "telephone 2", "tel", "mobile", "numero telephone"),
    "client_external_id": ("numero cin", "cin", "identifiant client", "id client", "code client"),
    "brand": ("marque", "marque vehicule"),
    "registration": ("immatdef", "immatriculation definitive", "immatriculation", "matricule", "immapro", "immatriculation provisoire"),
    "net_premium": ("prime net", "prime nette"),
    "cash_premium": ("prime au comptant",),
    "total_premium": ("prime total", "prime totale", "prime ttc"),
    "net_payable": ("net a paye", "net a payer"),
    "receipt": ("num quittance", "numero quittance", "quittance"),
    "effective_date": ("date effet", "date d effet", "date debut"),
    "end_date": ("date echeance", "date fin", "date de fin"),
    "issue_date": ("date emission", "date d emission"),
}

REQUIRED_CONTRACT_FIELDS = {"policy_number", "client_name", "end_date"}
SUMMARY_PREFIXES = ("nombre total", "total ht", "total ttc", "total general", "sous total")
UPCOMING_SIGNATURE_FIELDS = {"category", "policy_number", "client_name", "effective_date", "end_date", "renewed_flag"}
BORDEREAU_SIGNATURE_FIELDS = {"event", "receipt", "total_premium"}


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def clean_text(value):
    if value in (None, ""):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def clean_policy(value):
    return re.sub(r"\s*/\s*", "/", clean_text(value))


def detect_import_type(mapping):
    fields = set(mapping)
    if UPCOMING_SIGNATURE_FIELDS <= fields:
        return ImportBatch.ImportType.UPCOMING
    if fields & BORDEREAU_SIGNATURE_FIELDS:
        return ImportBatch.ImportType.BORDEREAU
    if (
        "end_date" not in fields
        and "client_phone" in fields
        and fields & {"policy_number", "client_external_id", "client_name"}
    ):
        return ImportBatch.ImportType.CONTACTS
    return ImportBatch.ImportType.GENERAL


def header_map(headers):
    normalized = {}
    for index, header in enumerate(headers or ()):
        key = normalize(header)
        if key:
            normalized.setdefault(key, []).append(index)

    result = {}
    for field, aliases in ALIASES.items():
        indices = []
        for alias in aliases:
            indices.extend(normalized.get(alias, []))
        if indices:
            result[field] = indices
    return result


def row_value(row, mapping, field):
    indices = mapping.get(field, ())
    for index in indices:
        if index < len(row) and row[index] not in (None, ""):
            return row[index]
    return ""


def find_header(rows, scan_limit=30):
    best_index, best_mapping, best_rank = 0, {}, (-1, -1, 0)
    for index, row in enumerate(rows[:scan_limit]):
        mapping = header_map(row)
        rank = (len(REQUIRED_CONTRACT_FIELDS & mapping.keys()), len(mapping), -index)
        if rank > best_rank:
            best_index, best_mapping, best_rank = index, mapping, rank
    return best_index, best_mapping, best_rank


def read_rows(upload):
    """Lit le tableau Excel le plus pertinent et le recadre sur sa ligne d'en-têtes."""
    if not upload.name.lower().endswith((".xlsx", ".xls")):
        raise ValueError("Seuls les fichiers Excel .xlsx ou .xls sont acceptés.")

    upload.seek(0)
    try:
        workbook = load_workbook(upload, read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise ValueError(
            "Impossible de lire ce fichier Excel. Utilisez un fichier .xlsx ou le fichier .xls "
            "fourni par l’assureur."
        ) from exc

    try:
        best_rows, best_header_index, best_rank = [], 0, (-1, -1, 0, 0)
        for sheet_index, sheet in enumerate(workbook.worksheets):
            rows = list(sheet.iter_rows(values_only=True))
            header_index, _mapping, rank = find_header(rows)
            sheet_rank = (*rank[:2], -sheet_index, rank[2])
            if sheet_rank > best_rank:
                best_rows, best_header_index, best_rank = rows, header_index, sheet_rank
        return best_rows[best_header_index:] if best_rows else []
    finally:
        workbook.close()


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"date invalide : {text}")


def parse_decimal(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"montant invalide : {value}") from exc


def is_summary_row(row, mapping):
    if row_value(row, mapping, "client_name") or row_value(row, mapping, "end_date"):
        return False
    first_value = next((normalize(value) for value in row if value not in (None, "")), "")
    return any(first_value.startswith(prefix) for prefix in SUMMARY_PREFIXES)


def data_rows(rows, mapping):
    for line_number, row in enumerate(rows[1:], 2):
        if not any(value not in (None, "") for value in row):
            continue
        if is_summary_row(row, mapping):
            continue
        yield line_number, row


def analyze_rows(rows):
    analysis = {
        "total_rows": 0,
        "recognized": [],
        "errors": [],
        "valid": False,
        "import_type": ImportBatch.ImportType.GENERAL,
    }
    if not rows:
        analysis["errors"].append({"line": 1, "error": "Fichier vide"})
        return analysis

    mapping = header_map(rows[0])
    analysis["import_type"] = detect_import_type(mapping)
    analysis["recognized"] = [
        clean_text(rows[0][index])
        for index in sorted({index for indices in mapping.values() for index in indices})
    ]
    candidates = list(data_rows(rows, mapping))
    analysis["total_rows"] = len(candidates)
    contacts_only = analysis["import_type"] == ImportBatch.ImportType.CONTACTS
    missing = REQUIRED_CONTRACT_FIELDS - mapping.keys()
    if missing and not contacts_only:
        analysis["errors"].append({"line": 1, "error": "Colonnes obligatoires absentes : " + ", ".join(sorted(missing))})
        return analysis

    for line_number, row in candidates:
        try:
            if contacts_only:
                if not clean_text(row_value(row, mapping, "client_phone")):
                    raise ValueError("téléphone obligatoire")
            else:
                if not clean_text(row_value(row, mapping, "policy_number")) or not clean_text(row_value(row, mapping, "client_name")):
                    raise ValueError("police et assuré obligatoires")
                if not parse_date(row_value(row, mapping, "end_date")):
                    raise ValueError("date de fin obligatoire")
                for field in ("effective_date", "issue_date"):
                    parse_date(row_value(row, mapping, field))
                for field in ("net_premium", "cash_premium", "total_premium", "net_payable"):
                    parse_decimal(row_value(row, mapping, field))
        except Exception as exc:
            if len(analysis["errors"]) < 100:
                analysis["errors"].append({"line": line_number, "error": str(exc)})
    analysis["valid"] = not any(error["line"] == 1 for error in analysis["errors"])
    return analysis


def record_error(batch, line_number, exc):
    batch.rejected_rows += 1
    if len(batch.errors) < 100:
        batch.errors.append({"line": line_number, "error": str(exc)})


def save_batch(batch):
    batch.save(update_fields=["added_rows", "updated_rows", "rejected_rows", "errors"])
    return batch


def import_contact_rows(candidates, mapping, batch):
    parsed = []
    for line_number, row in candidates:
        try:
            phone = clean_text(row_value(row, mapping, "client_phone"))
            if not phone:
                raise ValueError("téléphone obligatoire")
            parsed.append({
                "line": line_number,
                "phone": phone,
                "external_id": clean_text(row_value(row, mapping, "client_external_id")),
                "policy": clean_text(row_value(row, mapping, "policy_number")),
                "name": clean_text(row_value(row, mapping, "client_name")),
            })
        except Exception as exc:
            record_error(batch, line_number, exc)

    external_ids = {item["external_id"] for item in parsed if item["external_id"]}
    policies = {item["policy"] for item in parsed if item["policy"]}
    names = {item["name"].lower() for item in parsed if item["name"]}
    clients_by_external_id = {
        client.external_id: client
        for client in Client.objects.filter(external_id__in=external_ids)
    }
    clients_by_policy = {
        contract.policy_number: contract.client
        for contract in Contract.objects.select_related("client").filter(policy_number__in=policies)
    }
    clients_by_name = {}
    if names:
        for client in Client.objects.annotate(import_name=Lower("name")).filter(import_name__in=names):
            clients_by_name.setdefault(client.name.lower(), client)

    changed_clients = {}
    for item in parsed:
        client = None
        if item["external_id"]:
            client = clients_by_external_id.get(item["external_id"])
        if client is None and item["policy"]:
            client = clients_by_policy.get(item["policy"])
        if client is None and item["name"]:
            client = clients_by_name.get(item["name"].lower())
        if client is None:
            record_error(batch, item["line"], ValueError("client introuvable avec les identifiants fournis"))
            continue
        client.phone = item["phone"]
        changed_clients[client.pk] = client
        batch.updated_rows += 1

    if changed_clients:
        now = timezone.now()
        for client in changed_clients.values():
            client.updated_at = now
        Client.objects.bulk_update(
            changed_clients.values(),
            ["phone", "updated_at"],
            batch_size=500,
        )
    return save_batch(batch)


CONTRACT_VALUE_FIELDS = (
    "category", "agent_reference", "agent_code", "event", "pack_code", "brand",
    "registration", "net_premium", "cash_premium", "total_premium", "net_payable",
    "effective_date", "end_date", "issue_date",
)


def policy_from_row(row, mapping, import_type):
    policy = clean_policy(row_value(row, mapping, "policy_number"))
    category = clean_text(row_value(row, mapping, "category"))
    if (
        import_type == ImportBatch.ImportType.UPCOMING
        and category
        and policy
        and "/" not in policy
    ):
        return f"{category}/{policy}"
    return policy


def indicates_renewed(value):
    flag = normalize(value)
    if not flag or flag.startswith("non ") or flag in {"non", "no", "0", "false"}:
        return False
    return flag in {"oui", "yes", "1", "true"} or "renouvel" in flag


def dates_match(left, right, tolerance_days=1):
    return bool(left and right and abs((left - right).days) <= tolerance_days)


def select_contract_candidate(item, contracts, claimed_ids):
    candidates = [
        contract
        for contract in contracts
        if contract.pk not in claimed_ids
        and dates_match(contract.end_date, item["values"]["end_date"])
    ]
    if item["import_type"] == ImportBatch.ImportType.BORDEREAU:
        candidates = [
            contract
            for contract in candidates
            if not contract.receipt or contract.from_upcoming_file
        ]
    if not candidates:
        return None
    incoming_end = item["values"]["end_date"]
    return min(
        candidates,
        key=lambda contract: (
            abs((contract.end_date - incoming_end).days),
            not contract.from_upcoming_file,
            bool(contract.receipt),
            contract.pk,
        ),
    )


def merge_contract_values(contract, item, client):
    incoming = item["values"]
    preserve_snapshot_end = (
        item["import_type"] == ImportBatch.ImportType.BORDEREAU
        and contract.from_upcoming_file
        and dates_match(contract.end_date, incoming["end_date"])
    )
    contract.client = client
    for field, value in incoming.items():
        if value in (None, ""):
            continue
        if field == "end_date" and preserve_snapshot_end:
            continue
        setattr(contract, field, value)
    if item["receipt"]:
        contract.receipt = item["receipt"]
    if item["import_type"] == ImportBatch.ImportType.UPCOMING:
        contract.from_upcoming_file = True


def import_contract_rows(rows, filename, user):
    mapping = header_map(rows[0]) if rows else {}
    candidates = list(data_rows(rows, mapping)) if rows else []
    import_type = detect_import_type(mapping)
    batch = ImportBatch.objects.create(
        filename=filename,
        import_type=import_type,
        imported_by=user,
        total_rows=len(candidates),
    )
    if not rows:
        batch.errors = [{"line": 1, "error": "Fichier vide"}]
        batch.rejected_rows = 1
        return save_batch(batch)

    contacts_only = import_type == ImportBatch.ImportType.CONTACTS
    missing = REQUIRED_CONTRACT_FIELDS - mapping.keys()
    if missing and not contacts_only:
        batch.errors = [{"line": 1, "error": "Colonnes obligatoires absentes : " + ", ".join(sorted(missing))}]
        batch.rejected_rows = batch.total_rows
        return save_batch(batch)
    if contacts_only:
        return import_contact_rows(candidates, mapping, batch)

    parsed = []
    for line_number, row in candidates:
        try:
            policy = policy_from_row(row, mapping, import_type)
            receipt = clean_text(row_value(row, mapping, "receipt"))
            name = clean_text(row_value(row, mapping, "client_name"))
            if not policy or not name:
                raise ValueError("police et assuré obligatoires")
            values = {
                "category": clean_text(row_value(row, mapping, "category")),
                "agent_reference": clean_text(row_value(row, mapping, "agent_reference")),
                "agent_code": clean_text(row_value(row, mapping, "agent_code")),
                "event": clean_text(row_value(row, mapping, "event")),
                "pack_code": clean_text(row_value(row, mapping, "pack_code")),
                "brand": clean_text(row_value(row, mapping, "brand")),
                "registration": clean_text(row_value(row, mapping, "registration")),
                "net_premium": parse_decimal(row_value(row, mapping, "net_premium")),
                "cash_premium": parse_decimal(row_value(row, mapping, "cash_premium")),
                "total_premium": parse_decimal(row_value(row, mapping, "total_premium")),
                "net_payable": parse_decimal(row_value(row, mapping, "net_payable")),
                "effective_date": parse_date(row_value(row, mapping, "effective_date")),
                "end_date": parse_date(row_value(row, mapping, "end_date")),
                "issue_date": parse_date(row_value(row, mapping, "issue_date")),
            }
            if not values["end_date"]:
                raise ValueError("date de fin obligatoire")
            parsed.append({
                "line": line_number,
                "key": (policy, receipt),
                "policy": policy,
                "receipt": receipt,
                "name": name,
                "external_id": clean_text(row_value(row, mapping, "client_external_id")),
                "phone": clean_text(row_value(row, mapping, "client_phone")),
                "import_type": import_type,
                "renewed": indicates_renewed(row_value(row, mapping, "renewed_flag")),
                "values": values,
            })
        except Exception as exc:
            record_error(batch, line_number, exc)

    if not parsed:
        return save_batch(batch)

    try:
        with transaction.atomic():
            policies = {item["policy"] for item in parsed}
            existing_contract_list = list(
                Contract.objects.select_related("client").filter(policy_number__in=policies)
            )
            existing_contracts = {
                (contract.policy_number, contract.receipt): contract
                for contract in existing_contract_list
            }
            contracts_by_policy = {}
            clients_by_policy = {}
            for contract in existing_contract_list:
                contracts_by_policy.setdefault(contract.policy_number, []).append(contract)
                clients_by_policy.setdefault(contract.policy_number, contract.client)

            external_ids = {item["external_id"] for item in parsed if item["external_id"]}
            names = {item["name"].lower() for item in parsed}
            clients_by_identity = {
                ("external", client.external_id): client
                for client in Client.objects.filter(external_id__in=external_ids)
            }
            if names:
                for client in Client.objects.annotate(import_name=Lower("name")).filter(import_name__in=names):
                    clients_by_identity.setdefault(("name", client.name.lower()), client)

            new_clients = {}
            changed_clients = {}
            for item in parsed:
                external_identity = (
                    ("external", item["external_id"])
                    if item["external_id"]
                    else None
                )
                name_identity = ("name", item["name"].lower())
                identity = external_identity or name_identity
                client = (
                    (clients_by_identity.get(external_identity) if external_identity else None)
                    or clients_by_policy.get(item["policy"])
                    or clients_by_identity.get(name_identity)
                    or new_clients.get(identity)
                )
                if client is None:
                    client = Client(
                        name=item["name"],
                        phone=item["phone"],
                        external_id=item["external_id"],
                    )
                    new_clients[identity] = client
                else:
                    if item["phone"] and client.phone != item["phone"]:
                        client.phone = item["phone"]
                    if item["external_id"] and not client.external_id:
                        client.external_id = item["external_id"]
                    if client.pk:
                        changed_clients[client.pk] = client
                clients_by_identity[identity] = client
                clients_by_identity.setdefault(name_identity, client)
                if external_identity:
                    clients_by_identity[external_identity] = client
                clients_by_policy.setdefault(item["policy"], client)

            if new_clients:
                Client.objects.bulk_create(list(new_clients.values()), batch_size=500)
            if changed_clients:
                now = timezone.now()
                for client in changed_clients.values():
                    client.updated_at = now
                Client.objects.bulk_update(
                    list(changed_clients.values()),
                    ["phone", "external_id", "updated_at"],
                    batch_size=500,
                )

            final_records = {}
            for item in parsed:
                final_records[item["key"]] = item

            termination_tokens = [normalize(value) for value in settings.TERMINATION_EVENTS]
            new_contracts = []
            changed_contracts = []
            terminated_contracts = []
            claimed_ids = set()
            now = timezone.now()
            for key, item in final_records.items():
                identity = (
                    ("external", item["external_id"])
                    if item["external_id"]
                    else ("name", item["name"].lower())
                )
                contract = existing_contracts.get(key)
                if contract is None:
                    contract = select_contract_candidate(
                        item,
                        contracts_by_policy.get(item["policy"], ()),
                        claimed_ids,
                    )
                if contract is None:
                    contract = Contract(
                        client=clients_by_identity[identity],
                        policy_number=item["policy"],
                        receipt=item["receipt"],
                        from_upcoming_file=(
                            item["import_type"] == ImportBatch.ImportType.UPCOMING
                        ),
                        **item["values"],
                    )
                    new_contracts.append(contract)
                    batch.added_rows += 1
                else:
                    claimed_ids.add(contract.pk)
                    merge_contract_values(
                        contract,
                        item,
                        clients_by_identity[identity],
                    )
                    contract.updated_at = now
                    changed_contracts.append(contract)
                    batch.updated_rows += 1
                event_norm = normalize(item["values"]["event"])
                if any(token in event_norm for token in termination_tokens):
                    contract.renewal_status = Contract.RenewalStatus.TERMINATED
                    terminated_contracts.append(contract)
                elif item["renewed"] and not contract.manually_terminated:
                    contract.renewal_status = Contract.RenewalStatus.RENEWED

            if new_contracts:
                Contract.objects.bulk_create(new_contracts, batch_size=500)
            if changed_contracts:
                Contract.objects.bulk_update(
                    changed_contracts,
                    [
                        "client",
                        "receipt",
                        *CONTRACT_VALUE_FIELDS,
                        "from_upcoming_file",
                        "renewal_status",
                        "updated_at",
                    ],
                    batch_size=500,
                )

            terminated_ids = [contract.pk for contract in terminated_contracts]
            existing_termination_ids = set(
                Termination.objects.filter(contract_id__in=terminated_ids).values_list("contract_id", flat=True)
            )
            Termination.objects.bulk_create([
                Termination(contract=contract, reason=contract.event, recorded_by=user)
                for contract in terminated_contracts
                if contract.pk not in existing_termination_ids
            ], batch_size=500)
    except Exception as exc:
        batch.added_rows = 0
        batch.updated_rows = 0
        batch.rejected_rows += len(parsed)
        if len(batch.errors) < 100:
            batch.errors.append({"line": 1, "error": f"Import annulé : {exc}"})

    return save_batch(batch)


def import_contracts(upload, user, expected_type=None):
    rows = read_rows(upload)
    detected_type = detect_import_type(header_map(rows[0])) if rows else ImportBatch.ImportType.GENERAL
    if expected_type and detected_type != expected_type:
        labels = dict(ImportBatch.ImportType.choices)
        detected_label = labels.get(detected_type, "Fichier Excel standard")
        expected_label = labels.get(expected_type, "ce type de fichier")
        raise ValueError(
            f"Ce fichier est détecté comme « {detected_label} ». "
            f"Déposez-le dans la case « {detected_label} » et non dans "
            f"« {expected_label} »."
        )
    return import_contract_rows(rows, upload.name, user)
