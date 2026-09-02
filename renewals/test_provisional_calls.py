from datetime import timedelta

from django.test import TestCase
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from .models import AuditEvent, CallInteraction, Client, Contract, ImportBatch, User
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
            "phone": "",
            "event": "Prorogation",
        }
        values.update(overrides)
        batch = import_contracts(
            provisional_csv_upload([
                [
                    "Police", "N° Attestation", "Date d'écheance",
                    "Provisoires délivrées", "Nature Evennement", "Assuré",
                    "Prime TTC", "N° Quittance", "Immatriculation",
                    "Date Effet", "Date fin/ Echéance", "Etat Contrat", "Téléphone",
                ],
                [
                    self.contract.policy_number, values["attestation"],
                    values["due_date"].strftime("%d/%m/%Y"), values["delivered"],
                    values["event"], self.contract.client.name, values["premium"],
                    self.contract.receipt, self.contract.registration,
                    self.contract.effective_date.strftime("%d/%m/%Y"),
                    (self.contract.end_date + timedelta(days=1)).strftime("%d/%m/%Y"),
                    values["status"], values["phone"],
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
        self.assertEqual(row.call_attempts, 1)
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
                self.assertEqual(row.call_attempts, 0)
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
            "call_context": self.contract.call_context_token,
            "call_result": CallInteraction.Result.VOICEMAIL,
        })
        self.assertEqual(response.status_code, 302)
        self.import_provisional()
        self.assertEqual(self.contract.provisional_calls_started_at, cycle_start)
        response = self.checklist(call_status="unavailable")
        self.assertEqual(response.context["pending_count"], 0)
        row = response.context["contracts"][0]
        self.assertEqual(row.last_call_result, CallInteraction.Result.VOICEMAIL)
        self.assertEqual(row.call_attempts, 1)
        self.assertEqual(self.contract.interactions.count(), 2)

    def test_repaired_legacy_step_shows_zero_attempts_without_deleting_history(self):
        self.contract.provisional_calls_started_at = timezone.now()
        self.contract.save(update_fields=["provisional_calls_started_at"])

        response = self.checklist(call_status="pending")
        row = response.context["contracts"][0]
        self.assertEqual(row.last_call_label, "À appeler")
        self.assertEqual(row.call_attempts, 0)
        self.assertContains(response, "0</b><small>tentative")
        self.assertEqual(self.contract.interactions.count(), 1)
        self.old_call.refresh_from_db()
        self.assertEqual(self.old_call.comment, "Appel conservé de la première provisoire")

    def test_attempts_count_only_phone_calls_at_or_after_current_cycle_start(self):
        cycle_start = timezone.now() - timedelta(hours=1)
        self.contract.provisional_calls_started_at = cycle_start
        self.contract.save(update_fields=["provisional_calls_started_at"])
        for channel, offset in (
            (CallInteraction.Channel.PHONE, -1),
            (CallInteraction.Channel.PHONE, 0),
            (CallInteraction.Channel.PHONE, 1),
            (CallInteraction.Channel.SMS, 2),
        ):
            CallInteraction.objects.create(
                contract=self.contract,
                employee=self.user,
                occurred_at=cycle_start + timedelta(seconds=offset),
                channel=channel,
                call_result=CallInteraction.Result.VOICEMAIL,
                renewal_status=self.contract.renewal_status,
            )

        row = self.checklist().context["contracts"][0]
        self.assertEqual(row.call_attempts, 2)
        self.assertEqual(row.last_call_at, cycle_start + timedelta(seconds=1))
        self.assertEqual(self.contract.interactions.count(), 5)

    def test_changed_due_date_alone_starts_a_new_step(self):
        self.import_provisional(due_date=timezone.localdate() + timedelta(days=35))
        self.assertIsNotNone(self.contract.provisional_calls_started_at)
        self.assertEqual(self.checklist().context["pending_count"], 1)

    def test_changed_attestation_without_progress_is_reported_as_ambiguous(self):
        batch = self.import_provisional(attestation="ATT-NEW")
        self.assertEqual(batch.rejected_rows, 1)
        self.assertIn("ambigu", batch.errors[0]["error"])
        self.assertEqual(self.contract.provisional_attestation, "ATT-1")
        self.assertIsNone(self.contract.provisional_calls_started_at)
        self.assertEqual(self.checklist().context["completed_count"], 1)

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
        response = self.checklist()
        self.assertEqual(response.context["completed_count"], 1)
        self.assertEqual(response.context["contracts"][0].call_attempts, 1)

    def test_old_file_cannot_revert_step_or_change_other_data(self):
        old_due = self.contract.provisional_due_date
        self.import_provisional(attestation="ATT-2", delivered=2, due_date=old_due + timedelta(days=30))
        self.client.post(reverse("call_checklist"), {
            "contract": self.contract.pk,
            "call_context": self.contract.call_context_token,
            "call_result": "answered",
        })
        cycle_start = self.contract.provisional_calls_started_at
        updated_at = self.contract.updated_at
        batch = self.import_provisional(
            attestation="ATT-1", delivered=1, due_date=old_due,
            premium=9999, phone="0612345678",
        )
        self.assertEqual((batch.added_rows, batch.updated_rows, batch.rejected_rows), (0, 0, 1))
        self.assertIn("nombre délivré inférieur", batch.errors[0]["error"])
        self.assertEqual(self.contract.provisional_delivered_count, 2)
        self.assertEqual(self.contract.provisional_attestation, "ATT-2")
        self.assertEqual(self.contract.provisional_due_date, old_due + timedelta(days=30))
        self.assertEqual(self.contract.provisional_calls_started_at, cycle_start)
        self.assertEqual(self.contract.updated_at, updated_at)
        self.assertEqual(self.contract.total_premium, 1000)
        self.assertEqual(self.contract.client.phone, "")
        self.assertEqual(self.contract.interactions.count(), 2)
        self.assertEqual(self.checklist().context["completed_count"], 1)

    def test_older_due_date_is_rejected_even_with_same_or_higher_count(self):
        old_due = self.contract.provisional_due_date
        for count in (1, 2):
            with self.subTest(count=count):
                batch = self.import_provisional(delivered=count, due_date=old_due - timedelta(days=1))
                self.assertEqual(batch.rejected_rows, 1)
                self.assertIn("échéance antérieure", batch.errors[0]["error"])
                self.assertEqual(self.contract.provisional_due_date, old_due)
                self.assertEqual(self.contract.provisional_delivered_count, 1)

    def test_lower_count_is_rejected_even_with_a_later_due_date(self):
        self.import_provisional(delivered=2)
        batch = self.import_provisional(delivered=1, due_date=self.contract.provisional_due_date + timedelta(days=30))
        self.assertEqual(batch.rejected_rows, 1)
        self.assertEqual(self.contract.provisional_delivered_count, 2)

    def test_old_active_file_cannot_reopen_closed_provisional_tracking(self):
        self.import_provisional(status="Terminé")
        self.assertFalse(self.contract.is_provisional)
        batch = self.import_provisional(status="En cours")
        self.assertEqual(batch.rejected_rows, 1)
        self.assertIn("déjà clôturé", batch.errors[0]["error"])
        self.assertFalse(self.contract.is_provisional)

    def test_stale_checklist_form_is_rejected_without_losing_filters(self):
        old_token = self.checklist().context["contracts"][0].call_context_token
        self.import_provisional(attestation="ATT-2", delivered=2)
        url = reverse("call_checklist") + "?call_status=pending&due_filter=all&page=2"
        audit_count = AuditEvent.objects.filter(action=AuditEvent.Action.CALL_RECORDED).count()
        response = self.client.post(url, {
            "contract": self.contract.pk,
            "call_context": old_token,
            "call_result": "answered",
        })
        self.assertEqual(response["Location"], url)
        self.assertEqual(self.contract.interactions.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action=AuditEvent.Action.CALL_RECORDED).count(), audit_count)
        refreshed = self.checklist()
        self.assertEqual(refreshed.context["pending_count"], 1)
        self.assertContains(refreshed, "actualisez la checklist")
        fresh = refreshed.context["contracts"][0].call_context_token
        self.client.post(url, {"contract": self.contract.pk, "call_context": fresh, "call_result": "answered"})
        self.assertEqual(self.contract.interactions.count(), 2)
        self.assertEqual(self.checklist().context["completed_count"], 1)

    def test_regression_guard_does_not_block_a_real_termination(self):
        self.import_provisional(attestation="ATT-2", delivered=2)
        batch = self.import_provisional(
            attestation="ATT-1", delivered=1, event="Résiliation", premium=-100,
        )
        self.assertEqual(batch.rejected_rows, 0)
        self.assertEqual(self.contract.renewal_status, Contract.RenewalStatus.TERMINATED)
        self.assertEqual(self.contract.end_date, self.contract.effective_date)
        self.assertEqual(self.contract.termination.premium, -100)
        self.assertEqual(self.checklist().context["contracts"].paginator.count, 0)
        self.assertEqual(self.contract.interactions.count(), 1)

    def test_new_contract_cycle_can_start_at_one_after_a_closed_tracking(self):
        self.import_provisional(delivered=2, status="Terminé")
        start = self.contract.end_date + timedelta(days=1)
        batch = import_contracts(provisional_csv_upload([
            [
                "Police", "N° Attestation", "Date d'écheance",
                "Provisoires délivrées", "Nature Evennement", "Assuré",
                "Prime TTC", "N° Quittance", "Immatriculation",
                "Date Effet", "Date fin/ Echéance", "Etat Contrat",
            ],
            [
                self.contract.policy_number, "NEW-CYCLE-1",
                (start + timedelta(days=30)).strftime("%d/%m/%Y"),
                1, "Prorogation", self.contract.client.name, 1100,
                "NEW-CYCLE", self.contract.registration, start.strftime("%d/%m/%Y"),
                (start + timedelta(days=365)).strftime("%d/%m/%Y"), "En cours",
            ],
        ]), self.user, expected_type=ImportBatch.ImportType.PROVISIONAL)
        self.assertEqual((batch.added_rows, batch.rejected_rows), (1, 0))
        new_contract = Contract.objects.get(receipt="NEW-CYCLE")
        self.assertTrue(new_contract.is_provisional)
        self.assertEqual(new_contract.provisional_delivered_count, 1)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.provisional_delivered_count, 2)
        self.assertFalse(self.contract.is_provisional)
        self.assertEqual(self.contract.interactions.count(), 1)

    def test_missing_or_modified_call_context_is_rejected(self):
        for invalid in ("", "invalid", self.contract.call_context_token + "x"):
            with self.subTest(token=invalid[:10]):
                self.client.post(reverse("call_checklist"), {
                    "contract": self.contract.pk, "call_context": invalid, "call_result": "answered",
                })
                self.assertEqual(self.contract.interactions.count(), 1)

    def test_call_context_cannot_be_used_for_another_contract(self):
        other = Contract.objects.create(
            client=self.contract.client, assigned_agent=self.user,
            policy_number="OTHER", receipt="OTHER", end_date=self.contract.end_date,
        )
        self.client.post(reverse("call_checklist"), {
            "contract": other.pk,
            "call_context": self.contract.call_context_token,
            "call_result": "answered",
        })
        self.assertEqual(other.interactions.count(), 0)

    def test_normal_contract_form_is_stale_after_provisional_activation(self):
        self.contract.is_provisional = False
        self.contract.save(update_fields=["is_provisional"])
        old_token = self.contract.call_context_token
        self.import_provisional()
        self.client.post(reverse("call_checklist"), {
            "contract": self.contract.pk, "call_context": old_token, "call_result": "answered",
        })
        self.assertEqual(self.contract.interactions.count(), 1)
        self.assertEqual(self.checklist().context["pending_count"], 1)

    def test_stale_detail_form_does_not_record_call_or_change_renewal_status(self):
        old_token = self.contract.call_context_token
        self.import_provisional(delivered=2)
        response = self.client.post(reverse("contract_detail", args=[self.contract.pk]), {
            "call_context": old_token,
            "channel": "phone", "call_result": "answered", "renewal_status": "renewed",
        }, follow=True)
        self.assertContains(response, "actualisez la fiche")
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.interactions.count(), 1)
        self.assertEqual(self.contract.renewal_status, Contract.RenewalStatus.TO_CONTACT)

    def test_same_reimport_or_premium_update_keeps_open_form_valid(self):
        old_token = self.contract.call_context_token
        self.import_provisional()
        self.import_provisional(premium=1100)
        self.assertEqual(self.contract.call_context_token, old_token)
        self.client.post(reverse("call_checklist"), {
            "contract": self.contract.pk, "call_context": old_token, "call_result": "answered",
        })
        self.assertEqual(self.contract.interactions.count(), 2)

    def test_call_context_is_in_both_rendered_forms(self):
        for url in (reverse("call_checklist"), reverse("contract_detail", args=[self.contract.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'name="call_context"')
                self.assertContains(response, self.contract.call_context_token)

    def test_import_and_call_lock_the_contract_row(self):
        original = QuerySet.select_for_update
        locked_models = []

        def track_lock(queryset, *args, **kwargs):
            if queryset.model is Contract:
                locked_models.append(kwargs.get("of"))
            return original(queryset, *args, **kwargs)

        with patch.object(QuerySet, "select_for_update", track_lock):
            self.import_provisional(delivered=2)
            self.client.post(reverse("call_checklist"), {
                "contract": self.contract.pk,
                "call_context": self.contract.call_context_token,
                "call_result": "answered",
            })
        self.assertEqual(locked_models, [("self",), ("self",)])
