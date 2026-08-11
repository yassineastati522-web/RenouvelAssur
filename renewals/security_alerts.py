"""Alertes techniques sans identifiants, IP ni données métier."""

import logging

from django.conf import settings

from .audit import record_audit_event
from .models import AuditEvent


logger = logging.getLogger("renewals.security")


def report_security_alert(outcome, *, actor=None, action=None):
    """Journalise l'événement et le signale à Sentry lorsqu'il est configuré."""
    audit_action = action or AuditEvent.Action.SECURITY_ALERT
    record_audit_event(
        actor=actor,
        action=audit_action,
        details={"outcome": outcome},
    )
    logger.warning("Alerte de sécurité: %s", outcome)
    if settings.SENTRY_DSN:
        import sentry_sdk

        sentry_sdk.capture_message(
            f"security:{outcome}",
            level="warning",
        )
