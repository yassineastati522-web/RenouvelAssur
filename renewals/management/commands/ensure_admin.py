import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from renewals.audit import record_audit_event
from renewals.models import AuditEvent


class Command(BaseCommand):
    help = "Crée le premier administrateur depuis les variables d'environnement, si nécessaire."

    def handle(self, *args, **options):
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_PASSWORD absent : création administrateur ignorée."
            )
            return

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={"email": email},
        )

        changed_fields = []
        if created or not user.check_password(password):
            try:
                validate_password(password, user=user)
            except ValidationError as exc:
                if created:
                    user.delete()
                raise CommandError("Mot de passe administrateur refusé : " + " ".join(exc.messages)) from exc
            user.set_password(password)
            changed_fields.append("password")
        if email and user.email != email:
            user.email = email
            changed_fields.append("email")
        if not user.is_staff:
            user.is_staff = True
            changed_fields.append("is_staff")
        if not user.is_superuser:
            user.is_superuser = True
            changed_fields.append("is_superuser")
        if hasattr(user, "role") and user.role != "admin":
            user.role = "admin"
            changed_fields.append("role")

        if changed_fields:
            user.save(update_fields=changed_fields)

        record_audit_event(
            actor=None,
            action=(
                AuditEvent.Action.USER_CREATED
                if created
                else AuditEvent.Action.USER_UPDATED
            ),
            target=user,
            details={
                "changed_fields": [
                    field for field in changed_fields if field != "password"
                ],
            },
        )

        action = "créé" if created else "mis à jour et vérifié"
        self.stdout.write(self.style.SUCCESS(f"Administrateur {username} {action}."))
