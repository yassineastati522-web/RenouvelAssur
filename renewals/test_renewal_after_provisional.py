from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CallInteraction, Client, Contract, ImportBatch, User
from .services import import_contracts
from .tests import excel_upload, provisional_csv_upload


class RenewalAfterProvisionalTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.clock = patch("django.utils.timezone.now", return_value=self.now)
        self.mock_now = self.clock.start()
        self.addCleanup(self.clock.stop)
        call_clock = patch.object(
            CallInteraction._meta.get_field("occurred_at"), "get_default",
            side_effect=lambda: timezone.now(),
        )
        call_clock.start()
        self.addCleanup(call_clock.stop)
        self.today = timezone.localdate(self.now)
        self.user = User.objects.create_user("agent-renouvellement", role=User.Role.AGENT)
        self.client.force_login(self.user)
        self.contract = Contract.objects.create(
            client=Client.objects.create(name="Client test renouvellement"),
            assigned_agent=self.user,
            category="8", policy_number="8/FINAL-TEST", receipt="Q-FINAL",
            registration="123-A-4", total_premium=1000,
            effective_date=self.today - timedelta(days=60),
            end_date=self.today + timedelta(days=120),
            is_provisional=True, provisional_status="En cours",
            provisional_attestation="ATT-2", provisional_delivered_count=2,
            provisional_allowed_count=2,
            provisional_due_date=self.today - timedelta(days=1),
            provisional_calls_started_at=self.now - timedelta(days=30),
        )
        self.old_call = CallInteraction.objects.create(
            contract=self.contract, employee=self.user,
            occurred_at=self.now - timedelta(days=2),
            call_result=CallInteraction.Result.ANSWERED,
            comment="Appel de la dernière provisoire, à conserver",
        )

    def import_upcoming(self):
        batch = import_contracts(excel_upload([
            ["cat", "numero_police", "assure", "date_effet", "date_echeance", "renouvele", "immatriculation"],
            [
                "8", "FINAL-TEST", self.contract.client.name,
                self.contract.effective_date.isoformat(), self.contract.end_date.isoformat(),
                "non renouvele", self.contract.registration,
            ],
        ]), self.user, expected_type=ImportBatch.ImportType.UPCOMING)
        self.assertEqual((batch.added_rows, batch.updated_rows, batch.rejected_rows), (0, 1, 0))
        self.contract.refresh_from_db()
        self.assertEqual(Contract.objects.count(), 1)
        return batch

    def import_provisional(self, due_date=None, attestation="ATT-2", delivered=2):
        batch = import_contracts(provisional_csv_upload([
            [
                "Police", "N° Attestation", "Date d'écheance", "Provisoires délivrées",
                "Nature Evennement", "Assuré", "Prime TTC", "N° Quittance",
                "Immatriculation", "Date Effet", "Date fin/ Echéance", "Etat Contrat",
            ],
            [
                self.contract.policy_number, attestation,
                (due_date or self.contract.provisional_due_date).isoformat(), delivered,
                "Prorogation", self.contract.client.name, 1000, self.contract.receipt,
                self.contract.registration, self.contract.effective_date.isoformat(),
                (self.contract.end_date + timedelta(days=1)).isoformat(), "En cours",
            ],
        ]), self.user, expected_type=ImportBatch.ImportType.PROVISIONAL)
        self.contract.refresh_from_db()
        return batch

    def checklist(self, **filters):
        response = self.client.get(reverse("call_checklist"), filters)
        self.assertEqual(response.status_code, 200)
        return response

    def advance_to(self, instant):
        self.mock_now.return_value = instant
        # Les sessions expirent à minuit : simuler une reconnexion le jour testé.
        self.client.force_login(self.user)

    def record_call(self, result="answered", url=None, token=None):
        return self.client.post(url or reverse("call_checklist"), {
            "contract": self.contract.pk,
            "call_context": token or self.contract.call_context_token,
            "call_result": result,
        })

    def test_overdue_provisional_without_upcoming_import_stays_hidden(self):
        self.assertEqual(self.checklist().context["total_count"], 0)
        self.assertIsNone(self.contract.renewal_calls_started_at)

    def test_upcoming_import_restores_final_expiry_without_confirming_definitive(self):
        self.import_upcoming()
        response = self.checklist(call_status="pending")
        row = response.context["contracts"][0]
        self.assertEqual(row.action_date, self.contract.end_date)
        self.assertEqual(row.contact_due_date, self.contract.end_date)
        self.assertEqual(row.last_call_label, "À appeler")
        self.assertEqual(row.call_attempts, 1)
        self.assertEqual(response.context["pending_count"], 1)
        self.assertEqual(response.context["completed_count"], 0)
        self.assertTrue(self.contract.is_provisional)
        self.assertEqual(self.contract.provisional_status, "En cours")
        self.assertEqual(self.contract.provisional_delivered_count, 2)
        self.assertEqual(self.contract.renewal_status, Contract.RenewalStatus.TO_CONTACT)
        self.assertEqual(self.contract.total_premium, 1000)
        self.assertEqual(self.contract.renewal_calls_started_at, self.now)
        self.assertContains(response, "Renouvellement du contrat")
        self.assertContains(response, "Remise de la définitive non confirmée")
        self.assertNotContains(response, "Attestation définitive à remettre")
        detail = self.client.get(reverse("contract_detail", args=[self.contract.pk]))
        self.assertContains(detail, "RENOUVELLEMENT DU CONTRAT")
        self.assertContains(detail, self.old_call.comment)
        self.assertContains(detail, "Échéance provisoire enregistrée")

    def test_previous_unavailable_call_does_not_hide_the_new_action(self):
        for result in ("voicemail", "unreachable", "answered"):
            with self.subTest(result=result):
                self.old_call.call_result = result
                self.old_call.save(update_fields=["call_result"])
                self.import_upcoming()
                response = self.checklist()
                self.assertEqual(response.context["pending_count"], 1)
                self.assertEqual(response.context["unavailable_count"], 0)
                self.assertEqual(response.context["completed_count"], 0)

    def test_identical_monthly_and_provisional_imports_preserve_new_calls(self):
        self.import_upcoming()
        cycle_start = self.contract.renewal_calls_started_at
        self.advance_to(self.now + timedelta(minutes=5))
        url = reverse("call_checklist") + "?call_status=pending&due_filter=all&page=2"
        response = self.record_call("voicemail", url=url)
        self.assertEqual(response["Location"], url)
        self.advance_to(self.now + timedelta(days=1))
        self.import_upcoming()
        batch = self.import_provisional()
        self.assertEqual(batch.rejected_rows, 0)
        self.assertEqual(self.contract.renewal_calls_started_at, cycle_start)
        response = self.checklist(call_status="unavailable")
        self.assertEqual(response.context["pending_count"], 0)
        self.assertEqual(response.context["unavailable_count"], 1)
        row = response.context["contracts"][0]
        self.assertEqual(row.last_call_result, "voicemail")
        self.assertEqual(row.call_attempts, 2)
        self.assertEqual(self.contract.interactions.count(), 2)

    def test_future_provisional_remains_active_until_the_next_local_midnight(self):
        self.contract.provisional_due_date = self.today + timedelta(days=2)
        self.contract.save(update_fields=["provisional_due_date"])
        old_token = self.contract.call_context_token
        self.import_upcoming()
        transition = timezone.make_aware(datetime.combine(
            self.contract.provisional_due_date + timedelta(days=1), datetime.min.time(),
        ), timezone.get_default_timezone())
        self.assertEqual(self.contract.renewal_calls_started_at, transition)
        self.assertEqual(self.contract.call_context_token, old_token)
        self.advance_to(transition - timedelta(seconds=1))
        response = self.checklist()
        self.assertEqual(response.context["contracts"][0].action_date, self.contract.provisional_due_date)
        self.assertEqual(response.context["completed_count"], 1)
        self.assertFalse(self.contract.is_renewal_call)
        self.advance_to(transition)
        response = self.checklist()
        self.assertEqual(response.context["contracts"][0].action_date, self.contract.end_date)
        self.assertEqual(response.context["pending_count"], 1)
        self.assertTrue(self.contract.is_renewal_call)
        self.assertNotEqual(self.contract.call_context_token, old_token)
        self.record_call(token=old_token)
        self.assertEqual(self.contract.interactions.count(), 1)
        self.record_call()
        self.assertEqual(self.contract.interactions.count(), 2)
        self.assertEqual(self.checklist().context["completed_count"], 1)

    def test_provisional_expiring_today_does_not_switch_early(self):
        self.contract.provisional_due_date = self.today
        self.contract.save(update_fields=["provisional_due_date"])
        self.import_upcoming()
        self.assertFalse(self.contract.is_renewal_call)
        self.assertEqual(self.checklist().context["contracts"][0].action_date, self.today)

    def test_later_provisional_reschedules_the_renewal_action(self):
        self.import_upcoming()
        self.record_call()
        old_token = self.contract.call_context_token
        new_due = self.today + timedelta(days=20)
        batch = self.import_provisional(new_due, attestation="ATT-UPDATED")
        self.assertEqual(batch.rejected_rows, 0)
        self.assertFalse(self.contract.is_renewal_call)
        response = self.checklist()
        self.assertEqual(response.context["contracts"][0].action_date, new_due)
        self.assertNotEqual(self.contract.call_context_token, old_token)
        self.advance_to(self.contract.renewal_calls_started_at)
        self.assertEqual(self.checklist().context["pending_count"], 1)
        self.assertEqual(self.contract.interactions.count(), 2)

    def test_call_on_detail_counts_for_renewal_without_changing_old_history(self):
        self.import_upcoming()
        response = self.client.post(reverse("contract_detail", args=[self.contract.pk]), {
            "call_context": self.contract.call_context_token,
            "channel": "phone", "call_result": "answered", "renewal_status": "to_contact",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.checklist().context["completed_count"], 1)
        self.assertEqual(self.contract.interactions.count(), 2)
        self.old_call.refresh_from_db()
        self.assertEqual(self.old_call.comment, "Appel de la dernière provisoire, à conserver")

    def test_filters_use_final_expiry_and_agent_scope_is_preserved(self):
        self.import_upcoming()
        self.assertEqual(self.checklist(due_filter="gt15").context["total_count"], 1)
        self.assertEqual(self.checklist(due_date=self.contract.end_date.strftime("%d/%m/%Y")).context["total_count"], 1)
        self.assertEqual(self.checklist(due_date=(self.contract.end_date + timedelta(days=1)).strftime("%d/%m/%Y")).context["total_count"], 0)
        other_agent = User.objects.create_user("autre-agent-renouvellement")
        self.contract.assigned_agent = other_agent
        self.contract.save(update_fields=["assigned_agent"])
        self.assertEqual(self.checklist().context["total_count"], 0)
        self.assertEqual(self.record_call().status_code, 404)

    def test_closed_contracts_do_not_reappear(self):
        for status in ("renewed", "terminated", "refused", "competitor"):
            with self.subTest(status=status):
                self.contract.renewal_status = status
                self.contract.save(update_fields=["renewal_status"])
                self.import_upcoming()
                self.assertEqual(self.contract.renewal_status, status)
                self.assertEqual(self.checklist().context["total_count"], 0)

    def test_normal_contract_keeps_existing_call_status(self):
        self.contract.is_provisional = False
        self.contract.save(update_fields=["is_provisional"])
        self.import_upcoming()
        self.assertIsNone(self.contract.renewal_calls_started_at)
        self.assertEqual(self.checklist().context["completed_count"], 1)

    def test_provisional_alone_does_not_infer_an_upcoming_import(self):
        self.import_provisional()
        self.assertIsNone(self.contract.renewal_calls_started_at)
        self.assertEqual(self.checklist().context["total_count"], 0)

    def test_expired_final_contract_is_not_shown_in_default_checklist(self):
        self.import_upcoming()
        self.advance_to(self.now + timedelta(days=121))
        self.assertEqual(self.checklist().context["total_count"], 0)

    def test_old_open_form_is_rejected_after_final_expiry_import(self):
        old_token = self.contract.call_context_token
        self.import_upcoming()
        self.record_call(token=old_token)
        self.assertEqual(self.contract.interactions.count(), 1)
        response = self.client.post(reverse("contract_detail", args=[self.contract.pk]), {
            "call_context": old_token,
            "channel": "phone", "call_result": "answered", "renewal_status": "renewed",
        })
        self.assertEqual(response.status_code, 302)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.renewal_status, "to_contact")
        self.assertEqual(self.contract.interactions.count(), 1)

    def test_provisional_equal_to_final_expiry_has_no_extra_renewal_stage(self):
        self.contract.provisional_due_date = self.contract.end_date
        self.contract.save(update_fields=["provisional_due_date"])
        self.import_upcoming()
        self.assertIsNone(self.contract.renewal_calls_started_at)
