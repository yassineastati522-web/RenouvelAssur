import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Cr?e le premier administrateur depuis les variables Vercel, si n?cessaire."

    def handle(self, *args, **options):
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_PASSWORD absent : cr?ation administrateur ignor?e."
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

        action = "cr??" if created else "mis ? jour et v?rifi?"
        self.stdout.write(self.style.SUCCESS(f"Administrateur {username} {action}."))
