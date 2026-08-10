from django.contrib import messages
from django.contrib.auth.views import PasswordChangeView
from django.db import transaction
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator

from .audit import record_audit_event
from .models import AuditEvent


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
