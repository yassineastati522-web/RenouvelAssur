from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from renewals.models import CallInteraction, Client, Contract, Termination, User


class Command(BaseCommand):
    help = "Crée des comptes et un portefeuille de démonstration"

    def handle(self, *args, **options):
        admin, _ = User.objects.get_or_create(username="admin", defaults={"first_name": "Nadia", "last_name": "Admin", "role": User.Role.ADMIN, "is_staff": True, "is_superuser": True})
        admin.set_password("Admin123!"); admin.save()
        agent, _ = User.objects.get_or_create(username="agent", defaults={"first_name": "Youssef", "last_name": "Amrani", "role": User.Role.AGENT})
        agent.set_password("Agent123!"); agent.save()
        today = timezone.localdate()
        samples = [
            ("Sara El Idrissi", "0612345678", "POL-2026-001", "12345-A-6", 3, "to_contact", Decimal("4250")),
            ("Omar Benali", "0661987654", "POL-2026-002", "77821-B-8", 9, "callback", Decimal("6100")),
            ("Atlas Distribution SARL", "0522334455", "POL-2026-003", "19402-D-1", 18, "quote", Decimal("12800")),
            ("Khadija Mansouri", "0677889900", "POL-2026-004", "66218-A-3", 27, "wants", Decimal("3800")),
            ("Riad Services", "0655001122", "POL-2026-005", "90117-C-5", -5, "to_confirm", Decimal("9200")),
            ("Mehdi Alaoui", "0600112233", "POL-2026-006", "32011-A-2", -18, "terminated", Decimal("5100")),
            ("Imane Zahra", "0633221100", "POL-2026-007", "50144-B-7", 12, "renewed", Decimal("4750")),
        ]
        for index, (name, phone, policy, registration, days, status, premium) in enumerate(samples, 1):
            client, _ = Client.objects.get_or_create(name=name, defaults={"phone": phone, "external_id": f"CLI-{index:04}"})
            contract, created = Contract.objects.get_or_create(policy_number=policy, receipt=f"Q-{index:05}", defaults={
                "client": client, "assigned_agent": agent, "category": "Automobile", "agent_code": "AG-01",
                "registration": registration, "total_premium": premium, "net_premium": premium * Decimal("0.83"),
                "effective_date": today - timedelta(days=365-days), "end_date": today + timedelta(days=days),
                "issue_date": today - timedelta(days=370-days), "renewal_status": status,
            })
            if created and index in (2, 3, 4):
                CallInteraction.objects.create(contract=contract, employee=agent, call_result=CallInteraction.Result.ANSWERED if index != 3 else CallInteraction.Result.VOICEMAIL, renewal_status=status, comment="Échange de démonstration enregistré.", next_follow_up=timezone.now() + timedelta(days=1))
            if status == Contract.RenewalStatus.TERMINATED:
                contract.manually_terminated = True; contract.event = "Résiliation"; contract.save()
                Termination.objects.get_or_create(contract=contract, defaults={"reason": "Demande du client", "recorded_by": admin})
        self.stdout.write(self.style.SUCCESS("Données créées. Comptes : admin/Admin123! et agent/Agent123!"))
