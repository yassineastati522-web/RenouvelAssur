"""Opérations explicites sur les sessions des comptes de l'agence."""

from collections import Counter

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone


def revoke_user_sessions(users):
    """Supprime les sessions actives des utilisateurs en une seule lecture."""
    identifiers = {str(user.pk): user.pk for user in users if user.pk is not None}
    counts = Counter()
    session_keys = []
    for session in Session.objects.filter(
        expire_date__gte=timezone.now()
    ).iterator():
        user_id = str(session.get_decoded().get(SESSION_KEY, ""))
        if user_id in identifiers:
            session_keys.append(session.session_key)
            counts[identifiers[user_id]] += 1
    if session_keys:
        Session.objects.filter(session_key__in=session_keys).delete()
    return dict(counts)
