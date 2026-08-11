from django.contrib import admin
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from urllib.parse import urlencode
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from config.monitoring import scrub_sentry_event

from .admin import AuditEventAdmin
from .models import AuditEvent, User
from .session_management import revoke_user_sessions


def current_token(device):
    generator = TOTP(
        device.bin_key,
        device.step,
        device.t0,
        device.digits,
        device.drift,
    )
    return str(generator.token()).zfill(device.digits)


@override_settings(ADMIN_MFA_REQUIRED=True)
class AdminMFAFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "mfa-admin",
            password="StrongAdminPassword!42",
            role=User.Role.ADMIN,
            is_staff=True,
        )

    def test_admin_without_device_is_sent_to_secure_enrolment(self):
        response = self.client.post(reverse("login"), {
            "username": self.admin.username,
            "password": "StrongAdminPassword!42",
        })

        self.assertRedirects(
            response,
            reverse("mfa_setup"),
            fetch_redirect_response=False,
        )
        setup = self.client.get(reverse("mfa_setup"))
        self.assertEqual(setup.status_code, 200)
        self.assertContains(setup, "Activer la double authentification")
        self.assertTrue(TOTPDevice.objects.filter(
            user=self.admin,
            confirmed=False,
        ).exists())

    def test_enrolment_confirms_totp_and_creates_one_time_backup_codes(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("mfa_setup"))
        device = TOTPDevice.objects.get(user=self.admin, confirmed=False)

        response = self.client.post(reverse("mfa_setup"), {
            "otp_token": current_token(device),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Conservez vos codes de secours")
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(
            StaticToken.objects.filter(device__user=self.admin).count(),
            8,
        )
        self.assertEqual(
            self.client.session[DEVICE_ID_SESSION_KEY],
            device.persistent_id,
        )
        self.assertTrue(AuditEvent.objects.filter(
            actor=self.admin,
            action=AuditEvent.Action.MFA_ENABLED,
        ).exists())

    def test_existing_admin_device_requires_a_valid_second_factor(self):
        device = TOTPDevice.objects.create(
            user=self.admin,
            name="Téléphone",
            confirmed=True,
        )
        denied = self.client.post(reverse("login"), {
            "username": self.admin.username,
            "password": "StrongAdminPassword!42",
        })
        self.assertEqual(denied.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        accepted = self.client.post(reverse("login"), {
            "username": self.admin.username,
            "password": "StrongAdminPassword!42",
            "otp_token": current_token(device),
        })
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(
            self.client.session[DEVICE_ID_SESSION_KEY],
            device.persistent_id,
        )

    def test_backup_code_is_consumed_at_login(self):
        TOTPDevice.objects.create(
            user=self.admin,
            name="Téléphone",
            confirmed=True,
        )
        backup_device = StaticDevice.objects.create(
            user=self.admin,
            name="Codes de secours",
            confirmed=True,
        )
        StaticToken.objects.create(device=backup_device, token="backup42")

        response = self.client.post(reverse("login"), {
            "username": self.admin.username,
            "password": "StrongAdminPassword!42",
            "otp_token": "backup42",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(StaticToken.objects.filter(
            device=backup_device,
            token="backup42",
        ).exists())

    def test_old_unverified_admin_session_is_stopped_before_dashboard(self):
        TOTPDevice.objects.create(
            user=self.admin,
            name="Téléphone",
            confirmed=True,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('mfa_verify')}?{urlencode({'next': reverse('dashboard')})}",
            fetch_redirect_response=False,
        )

    def test_agent_login_does_not_require_an_otp(self):
        agent = User.objects.create_user(
            "mfa-agent",
            password="StrongAgentPassword!42",
            role=User.Role.AGENT,
        )

        response = self.client.post(reverse("login"), {
            "username": agent.username,
            "password": "StrongAgentPassword!42",
        })

        self.assertEqual(response.status_code, 302)


class SessionRevocationTests(TestCase):
    def test_all_active_sessions_for_selected_user_are_deleted(self):
        user = User.objects.create_user("session-user", password="secret")
        first = self.client_class()
        second = self.client_class()
        self.assertTrue(first.login(username=user.username, password="secret"))
        self.assertTrue(second.login(username=user.username, password="secret"))

        counts = revoke_user_sessions([user])

        self.assertEqual(counts, {user.pk: 2})
        self.assertEqual(first.get(reverse("dashboard")).status_code, 302)
        self.assertEqual(second.get(reverse("dashboard")).status_code, 302)

    def test_resetting_own_mfa_also_ends_the_current_admin_session(self):
        administrator = User.objects.create_superuser(
            "self-reset-admin",
            password="StrongAdminPassword!42",
        )
        TOTPDevice.objects.create(
            user=administrator,
            name="Téléphone",
            confirmed=True,
        )
        self.assertTrue(self.client.login(
            username=administrator.username,
            password="StrongAdminPassword!42",
        ))

        response = self.client.post(
            reverse("admin:renewals_user_changelist"),
            {
                "action": "reset_selected_mfa",
                "_selected_action": [str(administrator.pk)],
                "index": "0",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TOTPDevice.objects.filter(user=administrator).exists())
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditEvent.objects.filter(
            action=AuditEvent.Action.MFA_RESET,
            target_id=str(administrator.pk),
        ).exists())


class AuditExportTests(TestCase):
    def test_csv_export_neutralizes_spreadsheet_formulas_and_audits_export(self):
        administrator = User.objects.create_superuser(
            "export-admin",
            password="StrongAdminPassword!42",
        )
        formula_user = User.objects.create_user("=2+2", password="secret")
        event = AuditEvent.objects.create(
            actor=formula_user,
            action=AuditEvent.Action.LOGIN_SUCCEEDED,
            target_id="\t-10+10",
        )
        request = RequestFactory().post("/admin/renewals/auditevent/")
        request.user = administrator
        model_admin = AuditEventAdmin(AuditEvent, admin.site)

        response = model_admin.export_selected_csv(
            request,
            AuditEvent.objects.filter(pk=event.pk),
        )

        content = response.content.decode("utf-8-sig")
        self.assertIn("'=2+2", content)
        self.assertIn("'\t-10+10", content)
        self.assertTrue(AuditEvent.objects.filter(
            actor=administrator,
            action=AuditEvent.Action.AUDIT_EXPORTED,
            details={"exported_count": 1},
        ).exists())


class MonitoringPrivacyTests(TestCase):
    def test_sentry_scrubber_removes_request_content_and_identity(self):
        event = {
            "request": {
                "data": {"password": "secret"},
                "cookies": {"sessionid": "secret"},
                "query_string": "client=0612345678",
                "headers": {
                    "Authorization": "Bearer secret",
                    "User-Agent": "browser",
                },
            },
            "user": {"id": "12", "email": "client@example.com"},
            "breadcrumbs": [{"message": "client name"}],
            "extra": {"contract": "secret"},
            "exception": {"values": [{"stacktrace": {"frames": [
                {"vars": {"client": "secret"}, "function": "safe_name"},
            ]}}]},
        }

        scrubbed = scrub_sentry_event(event, {})

        self.assertNotIn("data", scrubbed["request"])
        self.assertNotIn("cookies", scrubbed["request"])
        self.assertNotIn("query_string", scrubbed["request"])
        self.assertNotIn("Authorization", scrubbed["request"]["headers"])
        self.assertEqual(scrubbed["user"], {"authenticated": True})
        self.assertNotIn("breadcrumbs", scrubbed)
        self.assertNotIn("extra", scrubbed)
        self.assertNotIn(
            "vars",
            scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0],
        )
