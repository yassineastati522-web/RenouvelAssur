import base64
from io import BytesIO

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django_otp import login as otp_login
from django_otp.forms import OTPTokenForm
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from .audit import record_audit_event
from .forms import AgencyAuthenticationForm, MFAActivationForm
from .models import AuditEvent
from .security_alerts import report_security_alert


def _has_totp(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def _safe_next(request, default="dashboard"):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse(default)


class AgencyLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = AgencyAuthenticationForm

    def get_success_url(self):
        user = self.request.user
        if (
            settings.ADMIN_MFA_REQUIRED
            and user.is_agency_admin
            and not _has_totp(user)
        ):
            return reverse("mfa_setup")
        return super().get_success_url()


@method_decorator(transaction.atomic, name="dispatch")
class AgencyPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change.html"
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        record_audit_event(
            actor=self.request.user,
            action=AuditEvent.Action.PASSWORD_CHANGED,
            target=self.request.user,
        )
        messages.success(
            self.request,
            "Votre mot de passe a été modifié. Les autres sessions ont été invalidées.",
        )
        return response


@login_required
def mfa_setup(request):
    if not request.user.is_agency_admin:
        return HttpResponseForbidden("Accès réservé aux administrateurs.")
    if _has_totp(request.user):
        messages.info(request, "La double authentification est déjà activée.")
        return redirect("dashboard")

    device = TOTPDevice.objects.filter(
        user=request.user,
        confirmed=False,
    ).order_by("pk").first()
    if device is None:
        device = TOTPDevice.objects.create(
            user=request.user,
            name="Application d’authentification",
            confirmed=False,
        )

    form = MFAActivationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked_device = TOTPDevice.objects.select_for_update().get(
                pk=device.pk,
                user=request.user,
                confirmed=False,
            )
            verified = locked_device.verify_token(
                form.cleaned_data["otp_token"]
            )
            if verified:
                locked_device.confirmed = True
                locked_device.save(update_fields=["confirmed"])
                StaticDevice.objects.filter(user=request.user).delete()
                backup_device = StaticDevice.objects.create(
                    user=request.user,
                    name="Codes de secours",
                    confirmed=True,
                )
                backup_codes = [
                    f"ra-{StaticToken.random_token()}"
                    for _ in range(8)
                ]
                StaticToken.objects.bulk_create([
                    StaticToken(device=backup_device, token=token)
                    for token in backup_codes
                ])
                otp_login(request, locked_device)
                record_audit_event(
                    actor=request.user,
                    action=AuditEvent.Action.MFA_ENABLED,
                    target=request.user,
                )
                return render(request, "registration/mfa_backup_codes.html", {
                    "backup_codes": backup_codes,
                })
        report_security_alert(
            "mfa_activation_failed",
            actor=request.user,
            action=AuditEvent.Action.MFA_FAILED,
        )
        form.add_error("otp_token", "Code incorrect. Vérifiez l’heure du téléphone.")

    image = qrcode.make(device.config_url)
    stream = BytesIO()
    image.save(stream, format="PNG")
    qr_data = base64.b64encode(stream.getvalue()).decode("ascii")
    return render(request, "registration/mfa_setup.html", {
        "form": form,
        "qr_data": qr_data,
        "manual_secret": base64.b32encode(device.bin_key).decode("ascii"),
    })


@login_required
def mfa_verify(request):
    if not request.user.is_agency_admin:
        return HttpResponseForbidden("Accès réservé aux administrateurs.")
    if not _has_totp(request.user):
        return redirect("mfa_setup")
    if request.user.is_verified():
        return redirect(_safe_next(request))

    form = OTPTokenForm(
        request.user,
        request=request,
        data=request.POST or None,
    )
    if request.method == "POST" and form.is_valid():
        otp_login(request, request.user.otp_device)
        return redirect(_safe_next(request))
    return render(request, "registration/mfa_verify.html", {
        "form": form,
        "next": _safe_next(request),
    })
