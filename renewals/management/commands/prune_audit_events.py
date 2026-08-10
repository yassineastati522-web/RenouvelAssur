from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from renewals.models import AuditEvent


class Command(BaseCommand):
    help = "Supprime les événements d'audit arrivés à expiration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.AUDIT_LOG_RETENTION_DAYS,
            help="Durée de conservation en jours.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirme réellement la suppression.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 30:
            raise CommandError("La durée de conservation doit être d'au moins 30 jours.")
        cutoff = timezone.now() - timedelta(days=days)
        expired = AuditEvent.objects.filter(occurred_at__lt=cutoff)
        count = expired.count()
        if not options["confirm"]:
            self.stdout.write(
                f"Simulation : {count} événement(s) antérieur(s) à la limite. "
                "Relancez avec --confirm pour les supprimer."
            )
            return
        expired.delete()
        self.stdout.write(self.style.SUCCESS(f"{count} événement(s) supprimé(s)."))
