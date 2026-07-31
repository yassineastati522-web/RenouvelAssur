import os
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from .models import CallInteraction, Client, Contract, ImportBatch, Termination, User
from .services import import_contracts


class HealthCheckTests(SimpleTestCase):
    def test_health_check_is_public(self):
        response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


def excel_upload(rows, filename="contrats.xlsx", leading_sheet=None):
    workbook = Workbook()
    sheet = workbook.active
    if leading_sheet is not None:
        sheet.title = "Instructions"
        sheet.append([leading_sheet])
        sheet = workbook.create_sheet("Bordereau")
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return SimpleUploadedFile(
        filename,
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def provisional_csv_upload(rows, filename="suivi_provisoires.csv"):
    content = "\r\n".join(";".join(str(value) for value in row) for row in rows)
    return SimpleUploadedFile(
        filename,
        content.encode("cp1252"),
        content_type="text/csv",
    )


class EnsureAdminCommandTests(TestCase):
    @patch.dict(os.environ, {
        "DJANGO_SUPERUSER_USERNAME": "admin",
        "DJANGO_SUPERUSER_EMAIL": "admin@example.com",
        "DJANGO_SUPERUSER_PASSWORD": "NewStrongPassword!42",
    })
    def test_existing_admin_password_is_updated(self):
        user = User.objects.create_user("admin", password="old-password")

        call_command("ensure_admin")

        user.refresh_from_db()
        self.assertTrue(user.check_password("NewStrongPassword!42"))
        self.assertEqual(user.email, "admin@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.role, User.Role.ADMIN)


class ImportServiceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="test", role=User.Role.ADMIN)

    def upload(self, premium="1 250,50"):
        return excel_upload([
            ["Police", "Assuré", "Téléphone", "Immatriculation", "Prime TTC", "Quittance", "Date Effet", "Date Fin"],
            ["P-001", "Client Test", "0611223344", "123-A-4", premium, "Q-01", "01/01/2026", "31/12/2026"],
        ])

    def test_import_adds_and_updates_without_duplicate(self):
        first = import_contracts(self.upload(), self.admin)
        self.assertEqual((first.added_rows, first.rejected_rows), (1, 0))
        second = import_contracts(self.upload("1500"), self.admin)
        self.assertEqual((second.updated_rows, Contract.objects.count()), (1, 1))
        self.assertEqual(str(Contract.objects.get().total_premium), "1500.00")

    def test_duplicate_rows_are_rejected_even_with_different_receipts(self):
        rows = [
            [
                "Police", "Assuré", "Immatriculation", "Nature Evenement",
                "Prime TTC", "Prime Net", "Quittance", "Date Effet", "Date Fin",
            ],
            [
                "P-DUP", "Client Double", "123-A-4", "Affaire nouvelle",
                1250, 1100, "Q-DUP-1", "01/01/2026", "31/12/2026",
            ],
            [
                "P-DUP", "Client Double", "123-A-4", "Affaire nouvelle",
                1250, 1100, "Q-DUP-2", "01/01/2026", "31/12/2026",
            ],
        ]

        batch = import_contracts(excel_upload(rows), self.admin)

        self.assertEqual((batch.added_rows, batch.rejected_rows), (1, 1))
        self.assertEqual(Contract.objects.count(), 1)
        self.assertIn("doublon ignoré", batch.errors[0]["error"])

    def test_duplicate_already_in_database_is_rejected(self):
        first = import_contracts(self.upload(), self.admin)
        self.assertEqual(first.added_rows, 1)
        duplicate = excel_upload([
            ["Police", "Assuré", "Téléphone", "Immatriculation", "Prime TTC", "Quittance", "Date Effet", "Date Fin"],
            ["P-001", "Client Test", "0611223344", "123-A-4", "1 250,50", "Q-02", "01/01/2026", "31/12/2026"],
        ])

        batch = import_contracts(duplicate, self.admin)

        self.assertEqual((batch.added_rows, batch.updated_rows, batch.rejected_rows), (0, 0, 1))
        self.assertEqual(Contract.objects.count(), 1)
        self.assertEqual(Contract.objects.get().receipt, "Q-01")

    def test_same_contract_with_different_premiums_keeps_the_highest_row(self):
        rows = [
            [
                "Police", "Assuré", "Immatriculation", "Prime TTC",
                "Quittance", "Date Effet", "Date Fin",
            ],
            [
                "8/0172880845", "AAZIZA YOUSSEF", "28831-A-48",
                "525,95", "Q-LOW-1", "08/11/2025", "08/11/2026",
            ],
            [
                "8/0172880845", "AAZIZA YOUSSEF", "28831 A 48",
                "525,93", "Q-LOW-2", "08/11/2025", "08/11/2026",
            ],
            [
                "8/0172880845", "AAZIZA YOUSSEF", "28831-A-48",
                "541,36", "Q-HIGH", "08/11/2025", "08/11/2026",
            ],
        ]

        batch = import_contracts(excel_upload(rows), self.admin)

        self.assertEqual(
            (batch.added_rows, batch.updated_rows, batch.rejected_rows),
            (1, 0, 2),
        )
        self.assertEqual(Contract.objects.count(), 1)
        contract = Contract.objects.get()
        self.assertEqual(contract.receipt, "Q-HIGH")
        self.assertEqual(str(contract.total_premium), "541.36")
        self.assertTrue(
            all("prime TTC inférieure" in error["error"] for error in batch.errors)
        )

    def test_lower_premium_cannot_replace_higher_existing_contract(self):
        higher = excel_upload([
            [
                "Police", "Assuré", "Immatriculation", "Prime TTC",
                "Quittance", "Date Effet", "Date Fin",
            ],
            [
                "P-HIGHEST", "Client Prime", "999-A-9", "900",
                "Q-HIGH", "01/01/2026", "31/12/2026",
            ],
        ])
        lower = excel_upload([
            [
                "Police", "Assuré", "Immatriculation", "Prime TTC",
                "Quittance", "Date Effet", "Date Fin",
            ],
            [
                "P-HIGHEST", "Client Prime", "999 A 9", "700",
                "Q-LOW", "01/01/2026", "31/12/2026",
            ],
        ])
        import_contracts(higher, self.admin)

        batch = import_contracts(lower, self.admin)

        self.assertEqual(
            (batch.added_rows, batch.updated_rows, batch.rejected_rows),
            (0, 0, 1),
        )
        self.assertEqual(Contract.objects.count(), 1)
        contract = Contract.objects.get()
        self.assertEqual(contract.receipt, "Q-HIGH")
        self.assertEqual(str(contract.total_premium), "900.00")
        self.assertIn("prime TTC supérieure", batch.errors[0]["error"])

    def test_bad_date_is_reported(self):
        upload = excel_upload([
            ["Police", "Assuré", "Date Fin"],
            ["P-2", "Test", "jamais"],
        ], filename="bad.xlsx")
        batch = import_contracts(upload, self.admin)
        self.assertEqual(batch.rejected_rows, 1)
        self.assertIn("date invalide", batch.errors[0]["error"])

    def test_phone_only_file_updates_existing_client_by_policy(self):
        import_contracts(self.upload(), self.admin)
        upload = excel_upload([
            ["Police", "Téléphone"],
            ["P-001", "0699999999"],
        ], filename="telephones.xlsx")
        batch = import_contracts(upload, self.admin)
        self.assertEqual((batch.updated_rows, batch.rejected_rows), (1, 0))
        self.assertEqual(Client.objects.get().phone, "0699999999")

    def test_insurer_bordereau_headers_and_totals_are_supported(self):
        headers = [
            "POLICE", "Nature Evenement", "CLIENT", "NUMERO_CIN", "DATE_EFFET", "DATE_ECHEANCE",
            "PRIME_TOTAL", "TIMBRE", "NET_A_PAYE", "NUMEROATTESTATION", "NUMEROATTESTATION_PROVISOIRE",
            "MARQUE", "IMMATDEF", "IMMAPRO", "ADRESSE", "VILE", "TELEPHONE", "NUM_QUITTANCE",
            "PRIME_NET", "PRIME_IPT", "TAXE", "TAXE_IPT", "ACCESSOIRE", "MONTANT_COMISSION", "TVA",
            "DATE_EMISSION", "EMMETEUR",
        ]
        contract_row = [
            "8/0142888495", "Prorogation", "EL BAOUNE MUSTAPHA", "AD24000", "19/07/2026", "19/07/2027",
            5020.35, 17, 4562.82, "0207241584", None, "HONDA", None, "88305-D-1",
            "OLD SLAMA AIN ATIQ TEMARA Maroc", "TEMARA", "0661769020", "146824844", 4286.78, 0,
            711.57, 0, 0, 503.2734, 45.7476, "18/07/2026", "m.astati",
        ]
        upload = excel_upload(
            [
                ["Bordereau quotidien du 18/07/2026"],
                [],
                headers,
                contract_row,
                [],
                ["Nombre total", 1],
                ["Total HT", "5 020,35"],
            ],
            filename="18_07_2026__bordereau.xlsx",
            leading_sheet="Consultez la feuille Bordereau",
        )

        batch = import_contracts(upload, self.admin)

        self.assertEqual((batch.total_rows, batch.added_rows, batch.rejected_rows), (1, 1, 0))
        contract = Contract.objects.select_related("client").get()
        self.assertEqual(contract.policy_number, "8/0142888495")
        self.assertEqual(contract.event, "Prorogation")
        self.assertEqual(contract.client.external_id, "AD24000")
        self.assertEqual(contract.client.phone, "0661769020")
        self.assertEqual(contract.brand, "HONDA")
        self.assertEqual(contract.registration, "88305-D-1")
        self.assertEqual(contract.receipt, "146824844")
        self.assertEqual(str(contract.total_premium), "5020.35")
        self.assertEqual(str(contract.net_premium), "4286.78")
        self.assertEqual(str(contract.net_payable), "4562.82")
        self.assertEqual(contract.end_date.isoformat(), "2027-07-18")

    def test_bordereau_midnight_boundary_becomes_previous_covered_day(self):
        upload = excel_upload([
            [
                "POLICE", "Nature Evenement", "CLIENT", "DATE_EFFET",
                "DATE_ECHEANCE", "PRIME_TOTAL", "NUM_QUITTANCE",
            ],
            [
                "8/BERRAQ-001", "Affaire nouvelle", "BERRAQ HOSSAM",
                "01/08/2025", "01/08/2026", 900, "Q-BERRAQ-001",
            ],
        ])

        batch = import_contracts(upload, self.admin)

        self.assertEqual((batch.added_rows, batch.rejected_rows), (1, 0))
        contract = Contract.objects.get()
        self.assertEqual(contract.client.name, "BERRAQ HOSSAM")
        self.assertEqual(contract.end_date, date(2026, 7, 31))

    def upcoming_upload(self, policy="0207161064", filename="echeances.xls"):
        return excel_upload([
            [
                "cat", "numero_police", "assure", "telephone", "telephone2",
                "adresse", "ville", "date_debut", "date_fin", "duree",
                "marque", "modele", "immatriculation", "libelle_intermediaire",
                "code_intermediaire", "Renouvele",
            ],
            [
                "8", policy, "KAOURAR ABDERRAZEK", "", "0636310031",
                "TEMARA", "TEMARA", "02/07/2026", "01/08/2026", "Ferme",
                "MERCEDES", "CLASSE C", "53972-E-1", "Agence test",
                "AG-01", "non renouvele",
            ],
        ], filename=filename)

    def bordereau_upload(self, policy="8/0207161064", filename="bordereau.xlsx"):
        return excel_upload([
            [
                "POLICE", "Nature Evenement", "CLIENT", "NUMERO_CIN",
                "DATE_EFFET", "DATE_ECHEANCE", "PRIME_TOTAL", "MARQUE",
                "IMMATDEF", "TELEPHONE", "NUM_QUITTANCE", "PRIME_NET",
                "DATE_EMISSION",
            ],
            [
                policy, "Affaire nouvelle", "KAOURAR ABDERRAZEK", "CIN-001",
                "02/07/2026", "02/08/2026", 650.66, "MERCEDES",
                "53972-E-1", "0636310031", "146669035", 570.75,
                "02/07/2026",
            ],
        ], filename=filename)

    def test_upcoming_insurer_file_with_xls_name_is_supported_and_idempotent(self):
        first = import_contracts(self.upcoming_upload(), self.admin)
        second = import_contracts(self.upcoming_upload(), self.admin)

        self.assertEqual(first.import_type, ImportBatch.ImportType.UPCOMING)
        self.assertEqual((first.added_rows, first.rejected_rows), (1, 0))
        self.assertEqual((second.updated_rows, second.rejected_rows), (1, 0))
        self.assertEqual(Contract.objects.count(), 1)
        contract = Contract.objects.select_related("client").get()
        self.assertEqual(contract.policy_number, "8/0207161064")
        self.assertEqual(contract.client.phone, "0636310031")
        self.assertEqual(contract.brand, "MERCEDES")
        self.assertEqual(contract.registration, "53972-E-1")
        self.assertEqual(contract.agent_reference, "Agence test")
        self.assertEqual(contract.agent_code, "AG-01")
        self.assertEqual(contract.end_date.isoformat(), "2026-08-01")
        self.assertTrue(contract.from_upcoming_file)
        self.assertIsNone(contract.total_premium)

    def test_upcoming_import_reuses_legacy_policy_without_category_prefix(self):
        client = Client.objects.create(
            name="KAOURAR ABDERRAZEK",
            phone="0636310031",
        )
        Contract.objects.create(
            client=client,
            category="8",
            policy_number="0207161064",
            registration="53972-E-1",
            effective_date=date(2026, 7, 2),
            end_date=date(2026, 8, 1),
        )

        batch = import_contracts(self.upcoming_upload(), self.admin)

        self.assertEqual((batch.added_rows, batch.updated_rows, batch.rejected_rows), (0, 1, 0))
        self.assertEqual(Contract.objects.count(), 1)
        self.assertEqual(Contract.objects.get().policy_number, "8/0207161064")

    def test_termination_date_comes_from_the_effective_date(self):
        upload = excel_upload([
            [
                "POLICE", "Nature Evenement", "CLIENT", "DATE_EFFET",
                "DATE_ECHEANCE", "NUM_QUITTANCE", "DATE_EMISSION",
            ],
            [
                "8/TERM-001", "Résiliation", "Client Résilié", "07/07/2026",
                "31/12/2026", "Q-TERM-001", "06/07/2026",
            ],
        ])

        batch = import_contracts(upload, self.admin)

        self.assertEqual((batch.added_rows, batch.rejected_rows), (1, 0))
        termination = Termination.objects.get()
        self.assertEqual(termination.date.isoformat(), "2026-07-07")

    def test_bordereau_enriches_upcoming_contract_without_overwriting_due_date(self):
        import_contracts(self.upcoming_upload(), self.admin)
        batch = import_contracts(self.bordereau_upload(), self.admin)

        self.assertEqual(batch.import_type, ImportBatch.ImportType.BORDEREAU)
        self.assertEqual((batch.added_rows, batch.updated_rows, batch.rejected_rows), (0, 1, 0))
        self.assertEqual(Contract.objects.count(), 1)
        contract = Contract.objects.select_related("client").get()
        self.assertEqual(contract.receipt, "146669035")
        self.assertEqual(contract.event, "Affaire nouvelle")
        self.assertEqual(str(contract.total_premium), "650.66")
        self.assertEqual(str(contract.net_premium), "570.75")
        self.assertEqual(contract.client.external_id, "CIN-001")
        self.assertEqual(contract.end_date.isoformat(), "2026-08-01")
        self.assertTrue(contract.from_upcoming_file)

    def test_provisional_csv_calculates_quota_and_updates_the_same_contract(self):
        headers = [
            "Police", "N° Attestation", "Date d'écheance",
            "Provisoires délivrées", "Nature Evennement", "Assuré",
            "Prime nette", "Prime TTC", "N° Quittance", "Immatriculation",
            "Date Effet", "Date fin/ Echéance", "Date Emission",
            "Etat Contrat",
        ]
        first_rows = [
            headers,
            [
                "PROV-3", "ATT-3", "31/01/2026", 1, "Affaire nouvelle",
                "Client trois mois", 500, 600, "QP-3", "111-A-1",
                "01/01/2026", "01/04/2026", "01/01/2026", "En cours",
            ],
            [
                "PROV-6", "ATT-6", "31/01/2026", 1, "Prorogation",
                "Client six mois", 700, 800, "QP-6", "222-A-2",
                "01/01/2026", "01/07/2026", "01/01/2026",
                "En cours?_csrf=valeur-invalide",
            ],
            [
                "PROV-12", "ATT-12", "01/04/2026", 3, "Prorogation",
                "Client un an", 900, 1000, "QP-12", "333-A-3",
                "01/01/2026", "01/01/2027", "01/01/2026", "En cours",
            ],
        ]

        batch = import_contracts(
            provisional_csv_upload(first_rows),
            self.admin,
            expected_type=ImportBatch.ImportType.PROVISIONAL,
        )

        self.assertEqual(batch.import_type, ImportBatch.ImportType.PROVISIONAL)
        self.assertEqual((batch.added_rows, batch.rejected_rows), (3, 0))
        quotas = {
            contract.policy_number: contract.provisional_allowed_count
            for contract in Contract.objects.all()
        }
        self.assertEqual(quotas, {"PROV-3": 1, "PROV-6": 2, "PROV-12": 3})
        six_month = Contract.objects.get(policy_number="PROV-6")
        self.assertTrue(six_month.is_provisional)
        self.assertEqual(six_month.provisional_delivered_count, 1)
        self.assertEqual(six_month.provisional_status, "En cours")
        self.assertEqual(
            six_month.provisional_action_label,
            "Prochaine provisoire à remettre",
        )
        annual = Contract.objects.get(policy_number="PROV-12")
        self.assertEqual(
            annual.provisional_action_label,
            "Attestation définitive à remettre",
        )

        updated_rows = [
            headers,
            [
                "PROV-6", "ATT-6-B", "02/03/2026", 2, "Prorogation",
                "Client six mois", 700, 800, "QP-6", "222-A-2",
                "01/01/2026", "01/07/2026", "01/01/2026", "En cours",
            ],
        ]
        update_batch = import_contracts(
            provisional_csv_upload(updated_rows),
            self.admin,
            expected_type=ImportBatch.ImportType.PROVISIONAL,
        )

        self.assertEqual(
            (update_batch.added_rows, update_batch.updated_rows, update_batch.rejected_rows),
            (0, 1, 0),
        )
        self.assertEqual(Contract.objects.count(), 3)
        six_month.refresh_from_db()
        self.assertEqual(six_month.provisional_delivered_count, 2)
        self.assertEqual(six_month.provisional_attestation, "ATT-6-B")
        self.assertEqual(six_month.provisional_due_date, date(2026, 3, 2))
        self.assertEqual(
            six_month.provisional_action_label,
            "Attestation définitive à remettre",
        )

    def test_provisional_import_rejects_count_above_contract_quota(self):
        upload = provisional_csv_upload([
            [
                "Police", "N° Attestation", "Date d'écheance",
                "Provisoires délivrées", "Assuré", "N° Quittance",
                "Immatriculation", "Date Effet", "Date fin/ Echéance",
                "Etat Contrat",
            ],
            [
                "PROV-INVALID", "ATT-X", "31/01/2026", 2,
                "Client invalide", "QP-X", "444-A-4", "01/01/2026",
                "01/04/2026", "En cours",
            ],
        ])

        batch = import_contracts(
            upload,
            self.admin,
            expected_type=ImportBatch.ImportType.PROVISIONAL,
        )

        self.assertEqual((batch.added_rows, batch.rejected_rows), (0, 1))
        self.assertIn("autorise 1", batch.errors[0]["error"])
        self.assertFalse(Contract.objects.exists())

    def test_new_contract_for_same_vehicle_marks_the_old_one_as_renewed(self):
        old_client = Client.objects.create(name="Ancien assuré")
        old_contract = Contract.objects.create(
            client=old_client,
            policy_number="OLD-VEHICLE",
            receipt="OLD-Q",
            registration="53972-E-1",
            effective_date=date(2025, 7, 1),
            end_date=date(2026, 7, 1),
        )
        upload = excel_upload([
            [
                "POLICE", "CLIENT", "DATE_EFFET", "DATE_ECHEANCE",
                "IMMATDEF", "NUM_QUITTANCE",
            ],
            [
                "NEW-VEHICLE", "Nouvel assuré", "02/07/2026",
                "01/07/2027", "53972 E 1", "NEW-Q",
            ],
        ])

        batch = import_contracts(upload, self.admin)

        self.assertEqual((batch.added_rows, batch.rejected_rows), (1, 0))
        new_contract = Contract.objects.get(policy_number="NEW-VEHICLE")
        old_contract.refresh_from_db()
        self.assertEqual(old_contract.renewal_status, Contract.RenewalStatus.RENEWED)
        self.assertEqual(old_contract.renewed_contract, new_contract)

    def test_upcoming_file_enriches_existing_bordereau_contract_in_reverse_order(self):
        import_contracts(self.bordereau_upload(policy="8/0207161123"), self.admin)
        batch = import_contracts(
            self.upcoming_upload(policy="0207161123"),
            self.admin,
        )

        self.assertEqual((batch.added_rows, batch.updated_rows, batch.rejected_rows), (0, 1, 0))
        self.assertEqual(Contract.objects.count(), 1)
        contract = Contract.objects.get()
        self.assertEqual(contract.policy_number, "8/0207161123")
        self.assertEqual(contract.receipt, "146669035")
        self.assertEqual(str(contract.total_premium), "650.66")
        self.assertEqual(contract.event, "Affaire nouvelle")
        self.assertEqual(contract.end_date.isoformat(), "2026-08-01")
        self.assertTrue(contract.from_upcoming_file)

    def test_large_excel_import_uses_a_bounded_number_of_queries(self):
        rows = [["POLICE", "CLIENT", "NUMERO_CIN", "DATE_ECHEANCE", "NUM_QUITTANCE"]]
        rows.extend([
            [f"POL-{index:04d}", f"Client {index}", f"CIN-{index:04d}", "31/12/2026", f"Q-{index:04d}"]
            for index in range(412)
        ])

        with CaptureQueriesContext(connection) as queries:
            batch = import_contracts(excel_upload(rows, filename="01_07_2026__bordereau.xlsx"), self.admin)

        self.assertEqual((batch.total_rows, batch.added_rows, batch.rejected_rows), (412, 412, 0))
        self.assertEqual(Client.objects.count(), 412)
        self.assertEqual(Contract.objects.count(), 412)
        self.assertLess(len(queries), 30)


class HighestPremiumDuplicateMigrationTests(TransactionTestCase):
    migrate_from = ("renewals", "0010_link_vehicle_renewals")
    migrate_to = ("renewals", "0011_keep_highest_premium_duplicates")

    def test_migration_keeps_highest_premium_and_moves_call_history(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        ClientModel = old_apps.get_model("renewals", "Client")
        ContractModel = old_apps.get_model("renewals", "Contract")
        CallInteractionModel = old_apps.get_model(
            "renewals",
            "CallInteraction",
        )

        client = ClientModel.objects.create(name="Client historique")
        lower = ContractModel.objects.create(
            client=client,
            policy_number="8/HIST-001",
            receipt="Q-HIST-LOW",
            registration="12345-A-6",
            effective_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            total_premium=Decimal("500.00"),
        )
        higher = ContractModel.objects.create(
            client=client,
            policy_number="8/HIST-001",
            receipt="Q-HIST-HIGH",
            registration="12345 A 6",
            effective_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            total_premium=Decimal("750.00"),
        )
        interaction = CallInteractionModel.objects.create(
            contract=lower,
            call_result="answered",
            renewal_status="to_contact",
        )
        middle = ContractModel.objects.create(
            client=client,
            policy_number="8/HIST-001",
            receipt="Q-HIST-MIDDLE",
            registration="12345/A/6",
            effective_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            total_premium=Decimal("600.00"),
        )
        first_predecessor = ContractModel.objects.create(
            client=client,
            policy_number="OLD-HIST-1",
            receipt="Q-OLD-HIST-1",
            registration="OLD-1",
            end_date=date(2025, 12, 31),
            total_premium=Decimal("100.00"),
            renewed_contract_id=lower.pk,
        )
        ContractModel.objects.create(
            client=client,
            policy_number="OLD-HIST-1",
            receipt="Q-OLD-HIST-1-DUPLICATE",
            registration="OLD 1",
            end_date=date(2025, 12, 31),
            total_premium=Decimal("50.00"),
        )
        second_predecessor = ContractModel.objects.create(
            client=client,
            policy_number="OLD-HIST-2",
            receipt="Q-OLD-HIST-2",
            registration="OLD-2",
            end_date=date(2025, 12, 31),
            renewed_contract_id=middle.pk,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        new_apps = executor.loader.project_state([self.migrate_to]).apps
        ContractModel = new_apps.get_model("renewals", "Contract")
        CallInteractionModel = new_apps.get_model(
            "renewals",
            "CallInteraction",
        )

        self.assertEqual(ContractModel.objects.count(), 3)
        survivor = ContractModel.objects.get(policy_number="8/HIST-001")
        self.assertEqual(survivor.pk, higher.pk)
        self.assertEqual(survivor.receipt, "Q-HIST-HIGH")
        self.assertEqual(survivor.total_premium, Decimal("750.00"))
        interaction = CallInteractionModel.objects.get(pk=interaction.pk)
        self.assertEqual(interaction.contract_id, survivor.pk)
        first_predecessor = ContractModel.objects.get(
            pk=first_predecessor.pk,
        )
        second_predecessor = ContractModel.objects.get(
            pk=second_predecessor.pk,
        )
        predecessor_links = {
            first_predecessor.renewed_contract_id,
            second_predecessor.renewed_contract_id,
        }
        self.assertEqual(predecessor_links, {None, survivor.pk})


class ExpiryBoundaryMigrationTests(TransactionTestCase):
    migrate_from = ("renewals", "0011_keep_highest_premium_duplicates")
    migrate_to = ("renewals", "0012_normalize_expiry_boundaries")

    def test_migration_corrects_all_stored_bordereau_boundaries(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        ClientModel = old_apps.get_model("renewals", "Client")
        ContractModel = old_apps.get_model("renewals", "Contract")
        client = ClientModel.objects.create(name="Audit des échéances")

        bordereau = ContractModel.objects.create(
            client=client,
            policy_number="BERRAQ-HISTORY",
            receipt="Q-BERRAQ-HISTORY",
            event="Affaire nouvelle",
            effective_date=date(2025, 8, 1),
            end_date=date(2026, 8, 1),
        )
        provisional = ContractModel.objects.create(
            client=client,
            policy_number="PROVISIONAL-HISTORY",
            receipt="Q-PROVISIONAL-HISTORY",
            is_provisional=True,
            effective_date=date(2026, 1, 1),
            end_date=date(2027, 1, 1),
        )
        upcoming = ContractModel.objects.create(
            client=client,
            policy_number="UPCOMING-HISTORY",
            receipt="Q-UPCOMING-HISTORY",
            event="Affaire nouvelle",
            end_date=date(2026, 8, 1),
            from_upcoming_file=True,
        )
        manual = ContractModel.objects.create(
            client=client,
            policy_number="MANUAL-HISTORY",
            receipt="",
            end_date=date(2026, 8, 1),
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        new_apps = executor.loader.project_state([self.migrate_to]).apps
        ContractModel = new_apps.get_model("renewals", "Contract")

        self.assertEqual(
            ContractModel.objects.get(pk=bordereau.pk).end_date,
            date(2026, 7, 31),
        )
        self.assertEqual(
            ContractModel.objects.get(pk=provisional.pk).end_date,
            date(2026, 12, 31),
        )
        self.assertEqual(
            ContractModel.objects.get(pk=upcoming.pk).end_date,
            date(2026, 8, 1),
        )
        self.assertEqual(
            ContractModel.objects.get(pk=manual.pk).end_date,
            date(2026, 8, 1),
        )


class ApplicationFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("agent", password="secret", role=User.Role.AGENT)
        self.client_obj = Client.objects.create(name="Client", phone="0600000000")
        self.contract = Contract.objects.create(
            client=self.client_obj,
            assigned_agent=self.user,
            policy_number="P-1",
            receipt="Q-1",
            brand="DACIA",
            registration="12345-A-1",
            end_date=timezone.localdate() + timedelta(days=5),
        )
        self.client.login(username="agent", password="secret")

    def test_dashboard_and_contract_list_load(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        contract_list = self.client.get(reverse("contract_list"))
        self.assertContains(contract_list, "Client")
        self.assertContains(contract_list, "DACIA")

        detail = self.client.get(reverse("contract_detail", args=[self.contract.pk]))
        self.assertContains(detail, "Marque")
        self.assertContains(detail, "DACIA")

    def test_client_list_counts_only_distinct_accessible_contracts(self):
        Contract.objects.create(
            client=self.client_obj,
            assigned_agent=self.user,
            policy_number="P-2",
            receipt="Q-2",
            end_date=timezone.localdate() + timedelta(days=20),
        )
        other_agent = User.objects.create_user(
            "other-client-agent",
            password="secret",
            role=User.Role.AGENT,
        )
        Contract.objects.bulk_create([
            Contract(
                client=self.client_obj,
                assigned_agent=other_agent,
                policy_number=f"HIDDEN-{index}",
                receipt=f"Q-HIDDEN-{index}",
                end_date=timezone.localdate() + timedelta(days=30 + index),
            )
            for index in range(6)
        ])

        response = self.client.get(reverse("client_list"))

        self.assertEqual(response.status_code, 200)
        visible_client = next(
            client
            for client in response.context["clients"]
            if client.pk == self.client_obj.pk
        )
        self.assertEqual(visible_client.contract_count, 2)

    def test_renewal_list_uses_relative_periods_and_two_statuses(self):
        past_client = Client.objects.create(
            name="Client échu depuis dix jours",
            phone="0600000010",
        )
        Contract.objects.create(
            client=past_client,
            assigned_agent=self.user,
            policy_number="PAST-10",
            receipt="QP-10",
            end_date=timezone.localdate() - timedelta(days=10),
        )
        future_client = Client.objects.create(
            name="Client à dix jours",
            phone="0600000020",
        )
        Contract.objects.create(
            client=future_client,
            assigned_agent=self.user,
            policy_number="FUTURE-10",
            receipt="QF-10",
            end_date=timezone.localdate() + timedelta(days=10),
        )
        renewed_client = Client.objects.create(
            name="Client renouvelé hors période",
            phone="0600000030",
        )
        renewed = Contract.objects.create(
            client=renewed_client,
            assigned_agent=self.user,
            policy_number="RENEWED-OLD",
            receipt="QR-OLD",
            end_date=timezone.localdate() - timedelta(days=40),
            renewal_status=Contract.RenewalStatus.RENEWED,
        )

        minus_15 = self.client.get(reverse("contract_list"), {
            "period": "minus15",
            "status": "not_renewed",
        })
        self.assertContains(minus_15, "PAST-10")
        minus_7 = self.client.get(reverse("contract_list"), {
            "period": "minus7",
            "status": "not_renewed",
        })
        self.assertNotContains(minus_7, "PAST-10")

        plus_7 = self.client.get(reverse("contract_list"), {
            "period": "plus7",
            "status": "not_renewed",
        })
        self.assertContains(plus_7, self.contract.policy_number)
        self.assertNotContains(plus_7, "FUTURE-10")
        plus_15 = self.client.get(reverse("contract_list"), {
            "period": "plus15",
            "status": "not_renewed",
        })
        self.assertContains(plus_15, "FUTURE-10")

        renewed_list = self.client.get(reverse("contract_list"), {
            "period": "all",
            "status": "renewed",
        })
        self.assertContains(renewed_list, renewed.policy_number)
        self.assertNotContains(renewed_list, self.contract.policy_number)
        self.assertContains(renewed_list, 'value="renewed" selected')
        self.assertNotContains(renewed_list, 'name="agent"')
        self.assertNotContains(renewed_list, "Tous les statuts")
        self.assertNotContains(renewed_list, "À contacter</option>")

    def test_dashboard_links_to_all_renewed_contracts_without_percentage(self):
        renewed_client = Client.objects.create(
            name="Client portefeuille conservé",
            phone="0600000040",
        )
        Contract.objects.create(
            client=renewed_client,
            assigned_agent=self.user,
            policy_number="RENEWED-DASHBOARD",
            receipt="QR-DASHBOARD",
            end_date=timezone.localdate() - timedelta(days=90),
            renewal_status=Contract.RenewalStatus.RENEWED,
        )

        dashboard = self.client.get(reverse("dashboard"))

        self.assertContains(
            dashboard,
            f'{reverse("contract_list")}?status=renewed&amp;period=all',
        )
        self.assertNotContains(dashboard, 'class="rate"')
        self.assertNotContains(dashboard, 'role="progressbar"')

    def test_interaction_is_appended_and_status_updated(self):
        response = self.client.post(reverse("contract_detail", args=[self.contract.pk]), {
            "channel": "phone",
            "call_result": "answered",
            "renewal_status": "wants",
            "comment": "Intéressé",
        })
        self.assertRedirects(response, reverse("contract_detail", args=[self.contract.pk]))
        self.assertEqual(CallInteraction.objects.count(), 1)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.renewal_status, "wants")

    def test_only_an_admin_can_delete_a_contract_with_its_related_history(self):
        interaction = CallInteraction.objects.create(
            contract=self.contract,
            employee=self.user,
            call_result=CallInteraction.Result.ANSWERED,
            renewal_status=self.contract.renewal_status,
        )
        termination = Termination.objects.create(
            contract=self.contract,
            reason="Résiliation à supprimer",
            recorded_by=self.user,
        )
        delete_url = reverse("contract_delete", args=[self.contract.pk])

        denied = self.client.post(delete_url)
        self.assertEqual(denied.status_code, 302)
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk).exists())

        self.user.role = User.Role.ADMIN
        self.user.save(update_fields=["role"])
        confirmation = self.client.get(delete_url)
        self.assertContains(confirmation, "Supprimer définitivement")
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk).exists())

        response = self.client.post(delete_url, follow=True)
        self.assertRedirects(response, reverse("contract_list"))
        self.assertContains(response, "a été supprimé")
        self.assertFalse(Contract.objects.filter(pk=self.contract.pk).exists())
        self.assertFalse(CallInteraction.objects.filter(pk=interaction.pk).exists())
        self.assertFalse(Termination.objects.filter(pk=termination.pk).exists())
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_call_form_only_offers_the_three_requested_results(self):
        response = self.client.get(reverse("contract_detail", args=[self.contract.pk]))
        choices = list(response.context["form"].fields["call_result"].choices)
        self.assertEqual(choices, [
            ("answered", "Client appelé"),
            ("voicemail", "Boîte vocale"),
            ("unreachable", "Non joignable"),
        ])

    def test_call_checklist_records_a_phone_call(self):
        response = self.client.get(reverse("call_checklist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checklist des appels")
        self.assertContains(response, self.client_obj.name)
        self.assertContains(response, "Véhicule")
        self.assertContains(response, "DACIA")
        self.assertContains(response, "12345-A-1")
        self.assertContains(response, "Nb. tentatives")
        self.assertContains(response, "0</b><small>tentative")
        self.assertNotContains(response, 'name="comment"')

        response = self.client.post(reverse("call_checklist"), {
            "contract": self.contract.pk,
            "call_result": "voicemail",
            "comment": "Message laissé",
        })
        self.assertRedirects(response, reverse("call_checklist"))
        interaction = CallInteraction.objects.get()
        self.assertEqual(interaction.contract, self.contract)
        self.assertEqual(interaction.employee, self.user)
        self.assertEqual(interaction.channel, CallInteraction.Channel.PHONE)
        self.assertEqual(interaction.call_result, CallInteraction.Result.VOICEMAIL)
        self.assertEqual(interaction.comment, "Message laissé")
        self.assertEqual(interaction.renewal_status, self.contract.renewal_status)

        response = self.client.get(reverse("call_checklist"))
        self.assertContains(response, "Boîte vocale")
        self.assertContains(response, "1</b><small>tentative")
        self.assertContains(response, "checked")
        pending = self.client.get(reverse("call_checklist"), {"call_status": "pending"})
        self.assertNotContains(pending, self.contract.policy_number)

    def test_call_checklist_respects_the_agent_scope(self):
        other_agent = User.objects.create_user("other-agent", password="secret", role=User.Role.AGENT)
        other_client = Client.objects.create(name="Client hors portefeuille", phone="0612345678")
        other_contract = Contract.objects.create(
            client=other_client,
            assigned_agent=other_agent,
            policy_number="P-OTHER",
            receipt="Q-OTHER",
            end_date=timezone.localdate() + timedelta(days=10),
        )
        response = self.client.get(reverse("call_checklist"))
        self.assertNotContains(response, other_client.name)
        response = self.client.post(reverse("call_checklist"), {
            "contract": other_contract.pk,
            "call_result": "answered",
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CallInteraction.objects.exists())

    def test_call_checklist_rejects_an_unknown_result(self):
        response = self.client.post(reverse("call_checklist"), {
            "contract": self.contract.pk,
            "call_result": "busy",
        })
        self.assertRedirects(response, reverse("call_checklist"))
        self.assertFalse(CallInteraction.objects.exists())

    def test_call_checklist_filters_unavailable_by_latest_phone_result(self):
        voicemail_client = Client.objects.create(
            name="Client boîte vocale",
            phone="0611111111",
        )
        voicemail_contract = Contract.objects.create(
            client=voicemail_client,
            assigned_agent=self.user,
            policy_number="POL-VOICEMAIL",
            receipt="Q-VOICEMAIL",
            end_date=timezone.localdate() + timedelta(days=6),
        )
        CallInteraction.objects.create(
            contract=voicemail_contract,
            employee=self.user,
            call_result=CallInteraction.Result.VOICEMAIL,
            renewal_status=voicemail_contract.renewal_status,
        )

        unreachable_client = Client.objects.create(
            name="Client non joignable",
            phone="0622222222",
        )
        unreachable_contract = Contract.objects.create(
            client=unreachable_client,
            assigned_agent=self.user,
            policy_number="POL-UNREACHABLE",
            receipt="Q-UNREACHABLE",
            end_date=timezone.localdate() + timedelta(days=7),
        )
        CallInteraction.objects.create(
            contract=unreachable_contract,
            employee=self.user,
            call_result=CallInteraction.Result.UNREACHABLE,
            renewal_status=unreachable_contract.renewal_status,
        )

        answered_client = Client.objects.create(
            name="Client finalement joint",
            phone="0633333333",
        )
        answered_contract = Contract.objects.create(
            client=answered_client,
            assigned_agent=self.user,
            policy_number="POL-ANSWERED",
            receipt="Q-ANSWERED",
            end_date=timezone.localdate() + timedelta(days=8),
        )
        CallInteraction.objects.create(
            contract=answered_contract,
            employee=self.user,
            call_result=CallInteraction.Result.VOICEMAIL,
            renewal_status=answered_contract.renewal_status,
            occurred_at=timezone.now() - timedelta(minutes=5),
        )
        CallInteraction.objects.create(
            contract=answered_contract,
            employee=self.user,
            call_result=CallInteraction.Result.ANSWERED,
            renewal_status=answered_contract.renewal_status,
        )

        response = self.client.get(reverse("call_checklist"), {
            "call_status": "unavailable",
        })

        self.assertContains(response, "Indisponibles")
        self.assertContains(response, voicemail_contract.policy_number)
        self.assertContains(response, unreachable_contract.policy_number)
        self.assertNotContains(response, answered_contract.policy_number)
        self.assertNotContains(response, self.contract.policy_number)

        completed = self.client.get(reverse("call_checklist"), {
            "call_status": "completed",
        })
        self.assertContains(completed, answered_contract.policy_number)
        self.assertNotContains(completed, voicemail_contract.policy_number)
        self.assertNotContains(completed, unreachable_contract.policy_number)

    def test_call_checklist_filters_due_dates_and_keeps_ascending_order(self):
        self.client_obj.name = "Échéance cinq jours"
        self.client_obj.save(update_fields=["name", "updated_at"])
        self.contract.policy_number = "POL-05"
        self.contract.save(update_fields=["policy_number", "updated_at"])

        client_10 = Client.objects.create(name="Échéance dix jours", phone="0611111111")
        Contract.objects.create(
            client=client_10,
            assigned_agent=self.user,
            policy_number="POL-10",
            receipt="Q-10",
            end_date=timezone.localdate() + timedelta(days=10),
        )
        client_20 = Client.objects.create(name="Échéance vingt jours", phone="0622222222")
        Contract.objects.create(
            client=client_20,
            assigned_agent=self.user,
            policy_number="POL-20",
            receipt="Q-20",
            end_date=timezone.localdate() + timedelta(days=20),
        )
        expired_client = Client.objects.create(name="Échéance déjà passée", phone="0633333333")
        Contract.objects.create(
            client=expired_client,
            assigned_agent=self.user,
            policy_number="POL-PAST",
            receipt="Q-PAST",
            end_date=timezone.localdate() - timedelta(days=2),
        )

        all_response = self.client.get(reverse("call_checklist"), {"due_filter": "all"})
        content = all_response.content.decode()
        self.assertNotContains(all_response, "POL-PAST")
        self.assertLess(content.index("POL-05"), content.index("POL-10"))
        self.assertLess(content.index("POL-10"), content.index("POL-20"))

        expired = self.client.get(reverse("call_checklist"), {"due_filter": "expired"})
        self.assertContains(expired, "POL-PAST")
        self.assertNotContains(expired, "POL-05")
        self.assertNotContains(expired, "POL-10")
        self.assertNotContains(expired, "POL-20")

        after_7 = self.client.get(reverse("call_checklist"), {"due_filter": "gt7"})
        self.assertNotContains(after_7, "POL-05")
        self.assertContains(after_7, "POL-10")
        self.assertContains(after_7, "POL-20")

        after_15 = self.client.get(reverse("call_checklist"), {"due_filter": "gt15"})
        self.assertNotContains(after_15, "POL-05")
        self.assertNotContains(after_15, "POL-10")
        self.assertContains(after_15, "POL-20")

        date_range = self.client.get(reverse("call_checklist"), {
            "date_from": (timezone.localdate() + timedelta(days=8)).isoformat(),
            "date_to": (timezone.localdate() + timedelta(days=12)).isoformat(),
        })
        self.assertNotContains(date_range, "POL-05")
        self.assertContains(date_range, "POL-10")
        self.assertNotContains(date_range, "POL-20")
        self.assertNotContains(date_range, 'name="q"')
        self.assertContains(date_range, 'name="date_from"')
        self.assertContains(date_range, 'name="date_to"')

    def test_call_checklist_uses_and_explains_the_provisional_due_date(self):
        provisional_client = Client.objects.create(
            name="Client en provisoire",
            phone="0644444444",
        )
        provisional = Contract.objects.create(
            client=provisional_client,
            assigned_agent=self.user,
            policy_number="POL-PROV",
            receipt="Q-PROV",
            registration="888-A-8",
            effective_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=180),
            is_provisional=True,
            provisional_attestation="ATT-PROV-1",
            provisional_due_date=timezone.localdate() + timedelta(days=10),
            provisional_delivered_count=1,
            provisional_allowed_count=2,
            provisional_status="En cours",
        )

        response = self.client.get(reverse("call_checklist"))

        self.assertContains(response, "POL-PROV")
        self.assertContains(response, "Provisoire 1/2")
        self.assertContains(response, "Prochaine provisoire à remettre")
        self.assertContains(response, "ATT-PROV-1")
        self.assertContains(
            response,
            provisional.provisional_due_date.strftime("%d/%m/%Y"),
        )
        after_15 = self.client.get(reverse("call_checklist"), {"due_filter": "gt15"})
        self.assertNotContains(after_15, "POL-PROV")

        detail = self.client.get(
            reverse("contract_detail", args=[provisional.pk]),
        )
        self.assertContains(detail, "ÉCHÉANCE PROVISOIRE")
        self.assertContains(detail, "Fin du contrat")

        choice_response = self.client.post(
            reverse("contract_detail", args=[provisional.pk]),
            {
                "form_action": "provisional_plan",
                "provisional_selected_count": "1",
            },
        )
        self.assertRedirects(
            choice_response,
            reverse("contract_detail", args=[provisional.pk]),
        )
        provisional.refresh_from_db()
        self.assertEqual(provisional.provisional_selected_count, 1)
        self.assertEqual(provisional.provisional_target_count, 1)
        self.assertEqual(
            provisional.provisional_action_label,
            "Attestation définitive à remettre",
        )

        updated_checklist = self.client.get(reverse("call_checklist"))
        self.assertContains(updated_checklist, "Provisoire 1/1")
        self.assertContains(updated_checklist, "Choix client : 1 sur 2 autorisées")
        self.assertContains(
            updated_checklist,
            "Attestation définitive à remettre",
        )

    def test_pagination_uses_arrow_buttons_and_keeps_checklist_filters(self):
        clients = [
            Client(
                name=f"Client pagination {index:02d}",
                phone=f"0600{index:06d}",
            )
            for index in range(31)
        ]
        Client.objects.bulk_create(clients)
        Contract.objects.bulk_create([
            Contract(
                client=client,
                assigned_agent=self.user,
                policy_number=f"PAGE-{index:02d}",
                receipt=f"QP-{index:02d}",
                end_date=timezone.localdate() + timedelta(days=index + 10),
            )
            for index, client in enumerate(clients)
        ])

        first_page = self.client.get(reverse("call_checklist"), {
            "call_status": "pending",
            "due_filter": "gt7",
            "date_from": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "date_to": (timezone.localdate() + timedelta(days=100)).isoformat(),
        })

        self.assertContains(first_page, 'aria-label="Page suivante"')
        self.assertContains(first_page, "call_status=pending")
        self.assertContains(first_page, "due_filter=gt7")
        self.assertContains(first_page, "date_from=")
        self.assertContains(first_page, "date_to=")
        self.assertNotContains(first_page, "Suivant →")
        second_page = self.client.get(reverse("call_checklist"), {
            "page": 2,
            "call_status": "pending",
            "due_filter": "gt7",
            "date_from": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "date_to": (timezone.localdate() + timedelta(days=100)).isoformat(),
        })
        self.assertContains(second_page, 'aria-label="Page précédente"')
        self.assertContains(second_page, "2 / 2")

    def test_non_renewed_list_filters_only_by_due_date_interval(self):
        for days_ago, policy in ((20, "OLD-20"), (10, "OLD-10"), (2, "OLD-02")):
            client = Client.objects.create(name=f"Client {policy}", phone="0600000000")
            Contract.objects.create(
                client=client,
                assigned_agent=self.user,
                policy_number=policy,
                receipt=f"Q-{policy}",
                end_date=timezone.localdate() - timedelta(days=days_ago),
            )

        response = self.client.get(reverse("expired_list"), {
            "date_from": (timezone.localdate() - timedelta(days=15)).isoformat(),
            "date_to": (timezone.localdate() - timedelta(days=5)).isoformat(),
        })

        self.assertEqual(response.context["contracts"].paginator.count, 1)
        self.assertContains(response, "OLD-10")
        self.assertNotContains(response, "OLD-20")
        self.assertNotContains(response, "OLD-02")
        self.assertNotContains(response, 'name="q"')
        self.assertNotContains(response, 'name="status"')

    def test_terminated_list_shows_contract_count_per_client_within_agent_scope(self):
        self.contract.renewal_status = Contract.RenewalStatus.TERMINATED
        self.contract.save(update_fields=["renewal_status", "updated_at"])
        Termination.objects.create(contract=self.contract, reason="Résiliation client", recorded_by=self.user)

        second_contract = Contract.objects.create(
            client=self.client_obj,
            assigned_agent=self.user,
            policy_number="P-2",
            receipt="Q-2",
            end_date=timezone.localdate() + timedelta(days=30),
            renewal_status=Contract.RenewalStatus.TERMINATED,
        )
        Termination.objects.create(contract=second_contract, reason="Deuxième résiliation", recorded_by=self.user)

        other_agent = User.objects.create_user("termination-other", password="secret", role=User.Role.AGENT)
        hidden_contract = Contract.objects.create(
            client=self.client_obj,
            assigned_agent=other_agent,
            policy_number="P-HIDDEN",
            receipt="Q-HIDDEN",
            end_date=timezone.localdate() + timedelta(days=60),
            renewal_status=Contract.RenewalStatus.TERMINATED,
        )
        Termination.objects.create(contract=hidden_contract, reason="Hors portefeuille", recorded_by=other_agent)

        response = self.client.get(reverse("terminated_list"))

        self.assertEqual(response.status_code, 200)
        visible = list(response.context["terminations"])
        self.assertEqual(len(visible), 2)
        self.assertEqual({item.client_terminated_count for item in visible}, {2})
        self.assertContains(response, "2 contrats", count=2)
        self.assertNotContains(response, "P-HIDDEN")

    def test_terminated_contracts_are_excluded_from_upcoming_and_renewal_lists(self):
        status_client = Client.objects.create(name="Résilié par statut", phone="0600000001")
        Contract.objects.create(
            client=status_client,
            assigned_agent=self.user,
            policy_number="TERM-STATUS",
            receipt="QT-1",
            end_date=timezone.localdate() + timedelta(days=6),
            renewal_status=Contract.RenewalStatus.TERMINATED,
        )
        manual_client = Client.objects.create(name="Résilié manuellement", phone="0600000002")
        Contract.objects.create(
            client=manual_client,
            assigned_agent=self.user,
            policy_number="TERM-MANUAL",
            receipt="QT-2",
            end_date=timezone.localdate() + timedelta(days=7),
            manually_terminated=True,
        )
        relation_client = Client.objects.create(name="Résilié avec fiche", phone="0600000003")
        relation_contract = Contract.objects.create(
            client=relation_client,
            assigned_agent=self.user,
            policy_number="TERM-RELATION",
            receipt="QT-3",
            end_date=timezone.localdate() + timedelta(days=8),
        )
        Termination.objects.create(contract=relation_contract, reason="Résiliation enregistrée", recorded_by=self.user)

        dashboard = self.client.get(reverse("dashboard"))
        renewals = self.client.get(reverse("contract_list"), {"days": 30})
        checklist = self.client.get(reverse("call_checklist"))

        self.assertEqual(dashboard.context["stats"]["soon"], 1)
        self.assertEqual(renewals.context["contracts"].paginator.count, 1)
        for response in (dashboard, renewals, checklist):
            self.assertContains(response, self.contract.policy_number)
            self.assertNotContains(response, "TERM-STATUS")
            self.assertNotContains(response, "TERM-MANUAL")
            self.assertNotContains(response, "TERM-RELATION")

    def test_agent_can_import_excel_and_view_the_report(self):
        import_page = self.client.get(reverse("import_view"))
        self.assertEqual(import_page.status_code, 200)
        self.assertContains(import_page, "Importer le bordereau de production")
        self.assertContains(import_page, "Importer les échéances à venir")
        self.assertContains(import_page, "Importer le suivi des provisoires")

        upload = excel_upload([
            ["POLICE", "CLIENT", "DATE_ECHEANCE", "PRIME_TOTAL", "NUM_QUITTANCE"],
            ["AGENT-IMPORT-001", "Client importé par agent", "31/12/2026", 750, "QA-1"],
        ])
        response = self.client.post(reverse("import_view"), {
            "import_kind": ImportBatch.ImportType.BORDEREAU,
            "bordereau-file": upload,
        })

        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("import_report", args=[batch.pk]))
        self.assertEqual(batch.imported_by, self.user)
        self.assertTrue(Contract.objects.filter(policy_number="AGENT-IMPORT-001").exists())

        report = self.client.get(reverse("import_report", args=[batch.pk]))
        self.assertEqual(report.status_code, 200)
        self.assertContains(report, "Aucune erreur")


class ExcelImportFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("exceladmin", password="secret", role=User.Role.ADMIN)
        self.client.login(username="exceladmin", password="secret")

    def test_import_page_shows_three_separate_upload_areas(self):
        response = self.client.get(reverse("import_view"))

        self.assertContains(response, "Importer le bordereau de production")
        self.assertContains(response, "Importer les échéances à venir")
        self.assertContains(response, "Importer le suivi des provisoires")
        self.assertContains(response, 'name="bordereau-file"')
        self.assertContains(response, 'name="upcoming-file"')
        self.assertContains(response, 'name="provisional-file"')

    def test_provisional_csv_is_imported_from_the_web_form(self):
        upload = provisional_csv_upload([
            [
                "Police", "N° Attestation", "Date d'écheance",
                "Provisoires délivrées", "Assuré", "N° Quittance",
                "Immatriculation", "Date Effet", "Date fin/ Echéance",
                "Etat Contrat",
            ],
            [
                "WEB-PROV", "WEB-ATT-1", "31/01/2026", 1,
                "Client provisoire web", "WEB-QP-1", "777-A-7",
                "01/01/2026", "01/07/2026", "En cours",
            ],
        ])

        response = self.client.post(reverse("import_view"), {
            "import_kind": ImportBatch.ImportType.PROVISIONAL,
            "provisional-file": upload,
        })

        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("import_report", args=[batch.pk]))
        self.assertEqual(batch.import_type, ImportBatch.ImportType.PROVISIONAL)
        contract = Contract.objects.get(policy_number="WEB-PROV")
        self.assertTrue(contract.is_provisional)
        self.assertEqual(contract.provisional_allowed_count, 2)

    def test_excel_is_imported_directly(self):
        upload = excel_upload([
            ["POLICE", "CLIENT", "DATE_ECHEANCE", "PRIME_TOTAL", "NUM_QUITTANCE"],
            ["XLSX-001", "Client Excel", "31/12/2026", 2450, "QX-1"],
        ])
        response = self.client.post(reverse("import_view"), {
            "import_kind": ImportBatch.ImportType.BORDEREAU,
            "bordereau-file": upload,
        })
        self.assertRedirects(response, reverse("import_report", args=[1]))
        self.assertEqual(Contract.objects.get().policy_number, "XLSX-001")

    def test_insurer_upcoming_xls_is_imported_from_the_web_form(self):
        upload = excel_upload([
            [
                "cat", "numero_police", "assure", "telephone", "date_debut",
                "date_fin", "marque", "immatriculation", "Renouvele",
            ],
            [
                "8", "0207161064", "Client échéance", "0636310031",
                "02/07/2026", "01/08/2026", "MERCEDES", "53972-E-1",
                "non renouvele",
            ],
        ], filename="avis_echeances.xls")

        response = self.client.post(reverse("import_view"), {
            "import_kind": ImportBatch.ImportType.UPCOMING,
            "upcoming-file": upload,
        })

        self.assertRedirects(response, reverse("import_report", args=[1]))
        batch = ImportBatch.objects.get()
        self.assertEqual(batch.import_type, ImportBatch.ImportType.UPCOMING)
        contract = Contract.objects.get()
        self.assertEqual(contract.policy_number, "8/0207161064")
        self.assertTrue(contract.from_upcoming_file)

    def test_file_is_rejected_when_uploaded_in_the_wrong_area(self):
        upload = excel_upload([
            [
                "cat", "numero_police", "assure", "date_debut", "date_fin",
                "Renouvele",
            ],
            [
                "8", "0207161064", "Client échéance", "02/07/2026",
                "01/08/2026", "non renouvele",
            ],
        ], filename="avis_echeances.xls")

        response = self.client.post(reverse("import_view"), {
            "import_kind": ImportBatch.ImportType.BORDEREAU,
            "bordereau-file": upload,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Échéances à venir")
        self.assertContains(response, "Bordereau de production")
        self.assertFalse(Contract.objects.exists())

    def test_pdf_is_rejected(self):
        upload = SimpleUploadedFile("contrats.pdf", b"%PDF-factice", content_type="application/pdf")
        response = self.client.post(reverse("import_view"), {
            "import_kind": ImportBatch.ImportType.BORDEREAU,
            "bordereau-file": upload,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "format Excel")
        self.assertFalse(Contract.objects.exists())

    def test_corrupt_xlsx_is_reported_without_server_error(self):
        upload = SimpleUploadedFile(
            "contrats.xlsx",
            b"ceci-n-est-pas-un-classeur",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response = self.client.post(reverse("import_view"), {
            "import_kind": ImportBatch.ImportType.BORDEREAU,
            "bordereau-file": upload,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Impossible de lire ce fichier Excel")
