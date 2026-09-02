from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CallInteraction, Client, Contract, ImportBatch, User
from .services import import_contracts
from .tests import excel_upload, provisional_csv_upload


class ProvisionalCallCycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("agent-provisoire", role=User.Role.AGENT)
        self.client.force_login(self.user)
        today = timezone.localdate()
        self.contract = Contract.objects.create(
            client=Client.objects.create(name="Client provisoire"),
            assigned_agent=self.user,
            policy_number="PROV-CALL-CYCLE",
            receipt="Q-CYCLE",
            registration="123-A-1",
            event="Prorogation",
            total_premium=1000,
            effective_date=today - timedelta(days=35),
            end_date=today + timedelta(days=330),
            is_provisional=True,
            provisional_attestation="ATT-1",
            provisional_due_date=today + timedelta(days=5),
            provisional_delivered_count=1,
            provisional_allowed_count=3,
            provisional_status="En cours",
        )
        self.old_call = CallInteraction.objects.create(
            contract=self.contract,
            employee=self.user,
            occurred_at=timezone.now() - timedelta(days=1),
            call_result=CallInteraction.Result.ANSWERED,
            renewal_status=self.contract.renewal_status,
            comment="Appel conservé de la première provisoire",
        )

    def import_provisional(self, **overrides):
        values = {
            "attestation": self.contract.provisional_attestation,
            "due_date": self.contract.provisional_due_date,
            "delivered": self.contract.provisional_delivered_count,
            "premium": self.contract.total_premium,
            "status": "En cours",
        }
        values.update(overrides)
        batch = import_contracts(
            provisional_csv_upload([
                [
                    "Police", "N° Attestation", "Date d'écheance",
                    "Provisoires délivrées", "Nature Evennement", "Assuré",
                    "Prime TTC", "N° Quittance", "Immatriculation",
                    "Date Effet", "Date fin/ Echéance", "Etat Contrat",
                ],
                [
                    self.contract.policy_number, values["attestation"],
                    values["due_date"].strftime("%d/%m/%Y"), values["delivered"],
                    "Prorogation", self.contract.client.name, values["premium"],
                    self.contract.receipt, self.contract.registration,
                    self.contract.effective_date.strftime("%d/%m/%Y"),
                    (self.contract.end_date + timedelta(days=1)).strftime("%d/%m/%Y"),
                    values["status"],
                ],
            ]),
            self.user,
            expected_type=ImportBatch.ImportType.PROVISIONAL,
        )
        self.contract.refresh_from_db()
        self.assertEqual(Contract.objects.count(), 1)
        self.assertEqual(batch.added_rows, 0)
        return batch

    def checklist(self, **filters):
        response = self.client.get(reverse("call_checklist"), filters)
        self.assertEqual(response.status_code, 200)
        return response

    def test_existing_provisional_keeps_its_call_until_a_new_step(self):
        response = self.checklist()
        row = response.context["contracts"][0]
        self.assertIsNone(self.contract.provisional_calls_started_at)
        self.assertEqual(row.last_call_result, CallInteraction.Result.ANSWERED)
        self.assertEqual(response.context["completed_count"], 1)

    def test_new_step_resets_all_call_results_and_filters_but_keeps_history(self):
        for old_result in (
            CallInteraction.Result.ANSWERED,
            CallInteraction.Result.VOICEMAIL,
            CallInteraction.Result.UNREACHABLE,
        ):
            with self.subTest(old_result=old_result):
                self.old_call.call_result = old_result
                self.old_call.save(update_fields=["call_result"])
                batch = self.import_provisional(
                    attestation="ATT-2", delivered=2,
                    due_date=timezone.localdate() + timedelta(days=35),
                )
                if old_result == CallInteraction.Result.ANSWERED:
                    self.assertEqual(batch.updated_rows, 1)
                self.assertIsNotNone(self.contract.provisional_calls_started_at)
                response = self.checklist(call_status="pending")
                row = response.context["contracts"][0]
                self.assertIsNone(row.last_call_at)
                self.assertEqual(row.last_call_label, "À appeler")
                self.assertEqual(row.call_attempts, 1)  # Total historique conservé.
                self.assertEqual(response.context["pending_count"], 1)
                self.assertEqual(response.context["completed_count"], 0)
                self.assertEqual(response.context["unavailable_count"], 0)
                for status in ("completed", "unavailable"):
                    self.assertEqual(
                        self.checklist(call_status=status).context["contracts"].paginator.count,
                        0,
                    )
        self.assertEqual(self.contract.interactions.count(), 1)
        detail = self.client.get(reverse("contract_detail", args=[self.contract.pk]))
        self.assertContains(detail, self.old_call.comment)

    def test_call_for_new_step_updates_status_and_same_reimport_keeps_it(self):
        self.import_provisional(attestation="ATT-2", delivered=2)
        cycle_start = self.contract.provisional_calls_started_at
        response = self.client.post(reverse("call_checklist"), {
            "contract": self.contract.pk,
            "call_result": CallInteraction.Result.VOICEMAIL,
        })
        self.assertEqual(response.status_code, 302)
        self.import_provisional()
        self.assertEqual(self.contract.provisional_calls_started_at, cycle_start)
        response = self.checklist(call_status="unavailable")
        self.assertEqual(response.context["pending_count"], 0)
        row = response.context["contracts"][0]
        self.assertEqual(row.last_call_result, CallInteraction.Result.VOICEMAIL)
        self.assertEqual(row.call_attempts, 2)
        self.assertEqual(self.contract.interactions.count(), 2)

    def test_changed_due_date_alone_starts_a_new_step(self):
        self.import_provisional(due_date=timezone.localdate() + timedelta(days=35))
        self.assertIsNotNone(self.contract.provisional_calls_started_at)
        self.assertEqual(self.checklist().context["pending_count"], 1)

    def test_changed_attestation_alone_starts_a_new_step(self):
        self.import_provisional(attestation="ATT-NEW")
        self.assertIsNotNone(self.contract.provisional_calls_started_at)

    def test_changed_delivered_count_alone_starts_a_new_step(self):
        self.import_provisional(delivered=2)
        self.assertIsNotNone(self.contract.provisional_calls_started_at)

    def test_first_provisional_on_an_existing_contract_starts_a_new_step(self):
        self.contract.is_provisional = False
        self.contract.save(update_fields=["is_provisional"])
        self.import_provisional()
        self.assertTrue(self.contract.is_provisional)
        self.assertIsNotNone(self.contract.provisional_calls_started_at)
        self.assertEqual(self.checklist().context["pending_count"], 1)

    def test_premium_only_update_does_not_reset_calls(self):
        self.import_provisional(premium=1100)
        self.assertEqual(self.contract.total_premium, 1100)
        self.assertIsNone(self.contract.provisional_calls_started_at)
        self.assertEqual(self.checklist().context["completed_count"], 1)

    def test_missing_attestation_does_not_reset_or_clear_existing_attestation(self):
        self.import_provisional(attestation="", premium=1100)
        self.assertEqual(self.contract.provisional_attestation, "ATT-1")
        self.assertIsNone(self.contract.provisional_calls_started_at)

    def test_general_import_does_not_reset_provisional_calls(self):
        import_contracts(excel_upload([
            ["Police", "Assuré", "Immatriculation", "Prime TTC", "Quittance", "Date Effet", "Date Fin"],
            [
                self.contract.policy_number, self.contract.client.name,
                self.contract.registration, 1100, self.contract.receipt,
                self.contract.effective_date, self.contract.end_date,
            ],
        ]), self.user)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.total_premium, 1100)
        self.assertIsNone(self.contract.provisional_calls_started_at)
        self.assertEqual(self.checklist().context["completed_count"], 1)

    def test_client_plan_change_does_not_reset_calls(self):
        response = self.client.post(reverse("contract_detail", args=[self.contract.pk]), {
            "form_action": "provisional_plan",
            "provisional_selected_count": "1",
        })
        self.assertEqual(response.status_code, 302)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.provisional_selected_count, 1)
        self.assertIsNone(self.contract.provisional_calls_started_at)
        self.assertEqual(self.checklist().context["completed_count"], 1)

    def test_non_provisional_contract_keeps_its_lifetime_call_status(self):
        self.contract.is_provisional = False
        self.contract.provisional_calls_started_at = timezone.now()
        self.contract.save(update_fields=["is_provisional", "provisional_calls_started_at"])
        self.assertEqual(self.checklist().context["completed_count"], 1)
