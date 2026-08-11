"""Journal d'audit applicatif sans données métier ni identifiants clients."""

from .models import AuditEvent


SAFE_DETAIL_KEYS = {
    "added_rows",
    "changed_fields",
    "import_type",
    "exported_count",
    "new_status",
    "outcome",
    "previous_status",
    "provisional_count",
    "rejected_rows",
    "session_count",
    "updated_rows",
}


def _safe_value(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:100]
    if isinstance(value, (list, tuple)):
        return [str(item)[:50] for item in value[:30]]
    return str(value)[:100]


def record_audit_event(*, actor, action, target=None, details=None):
    """Enregistre uniquement des métadonnées explicitement autorisées.

    Les noms, téléphones, numéros de police, commentaires et contenus de
    fichiers ne sont jamais acceptés dans ``details``.
    """
    safe_details = {
        key: _safe_value(value)
        for key, value in (details or {}).items()
        if key in SAFE_DETAIL_KEYS
    }
    authenticated_actor = (
        actor
        if actor is not None
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "pk", None)
        else None
    )
    target_type = ""
    target_id = ""
    if target is not None:
        target_type = target._meta.label_lower[:80]
        target_id = str(target.pk)[:64]
    return AuditEvent.objects.create(
        actor=authenticated_actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=safe_details,
    )
