import csv
import json

from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.admin import UserAdmin
from django.db.models import Exists, OuterRef
from django.http import HttpResponse
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from .audit import record_audit_event
from .models import (
    AuditEvent,
    CallInteraction,
    Client,
    Contract,
    ImportBatch,
    Renewal,
    Termination,
    User,
)
from .session_management import revoke_user_sessions


MAX_AUDIT_EXPORT_ROWS = 10000


def spreadsheet_safe(value):
    """Neutralise les formules CSV sans altérer les valeurs normales."""
    text = "" if value is None else str(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def changed_field_names(form):
    return [
        field
        for field in form.changed_data
        if not field.lower().startswith("password")
    ]


class AuditedAdminMixin:
    audit_update_action = AuditEvent.Action.RECORD_UPDATED
    audit_delete_action = AuditEvent.Action.RECORD_DELETED

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change:
            record_audit_event(
                actor=request.user,
                action=self.audit_update_action,
                target=obj,
                details={"changed_fields": changed_field_names(form)},
            )

    def delete_model(self, request, obj):
        record_audit_event(
            actor=request.user,
            action=self.audit_delete_action,
            target=obj,
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset.only("pk"):
            record_audit_event(
                actor=request.user,
                action=self.audit_delete_action,
                target=obj,
            )
        super().delete_queryset(request, queryset)

@admin.register(User)
class AgencyUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + ((
        "Agence",
        {"fields": ("role", "must_change_password")},
    ),)
    add_fieldsets = UserAdmin.add_fieldsets + ((
        "Agence",
        {"fields": ("role",)},
    ),)
    list_display = (
        "username",
        "first_name",
        "last_name",
        "role",
        "mfa_enabled",
        "must_change_password",
        "is_active",
    )
    actions = ("revoke_selected_sessions", "reset_selected_mfa")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _mfa_enabled=Exists(TOTPDevice.objects.filter(
                user_id=OuterRef("pk"),
                confirmed=True,
            ))
        )

    @admin.display(boolean=True, ordering="_mfa_enabled", description="MFA")
    def mfa_enabled(self, obj):
        return obj._mfa_enabled

    @admin.action(description="Révoquer toutes les sessions sélectionnées")
    def revoke_selected_sessions(self, request, queryset):
        users = list(queryset)
        counts = revoke_user_sessions(users)
        for user in users:
            record_audit_event(
                actor=request.user,
                action=AuditEvent.Action.SESSIONS_REVOKED,
                target=user,
                details={"session_count": counts.get(user.pk, 0)},
            )
        if any(user.pk == request.user.pk for user in users):
            logout(request)
        self.message_user(
            request,
            f"{sum(counts.values())} session(s) révoquée(s).",
            messages.SUCCESS,
        )

    @admin.action(description="Réinitialiser la double authentification")
    def reset_selected_mfa(self, request, queryset):
        users = list(queryset)
        user_ids = [user.pk for user in users]
        TOTPDevice.objects.filter(user_id__in=user_ids).delete()
        StaticDevice.objects.filter(user_id__in=user_ids).delete()
        counts = revoke_user_sessions(users)
        for user in users:
            record_audit_event(
                actor=request.user,
                action=AuditEvent.Action.MFA_RESET,
                target=user,
                details={"session_count": counts.get(user.pk, 0)},
            )
        if any(user.pk == request.user.pk for user in users):
            logout(request)
        self.message_user(
            request,
            "Double authentification réinitialisée; les comptes concernés "
            "devront la configurer à leur prochaine connexion.",
            messages.WARNING,
        )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.must_change_password = True
        super().save_model(request, obj, form, change)
        record_audit_event(
            actor=request.user,
            action=(
                AuditEvent.Action.USER_UPDATED
                if change
                else AuditEvent.Action.USER_CREATED
            ),
            target=obj,
            details={"changed_fields": changed_field_names(form)},
        )

    def user_change_password(self, request, id, form_url=""):
        target = self.get_object(request, id)
        previous_hash = target.password if target is not None else None
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and target is not None:
            target.refresh_from_db()
            if previous_hash != target.password:
                if target.pk != request.user.pk:
                    target.must_change_password = True
                    target.save(update_fields=["must_change_password"])
                record_audit_event(
                    actor=request.user,
                    action=AuditEvent.Action.USER_UPDATED,
                    target=target,
                    details={"changed_fields": ["password_reset"]},
                )
        return response

    def delete_model(self, request, obj):
        record_audit_event(
            actor=request.user,
            action=AuditEvent.Action.USER_DELETED,
            target=obj,
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset.only("pk"):
            record_audit_event(
                actor=request.user,
                action=AuditEvent.Action.USER_DELETED,
                target=obj,
            )
        super().delete_queryset(request, queryset)

@admin.register(Client)
class ClientAdmin(AuditedAdminMixin, admin.ModelAdmin):
    audit_update_action = AuditEvent.Action.CLIENT_UPDATED
    list_display = ("name", "phone", "external_id", "updated_at")
    search_fields = ("name", "phone", "external_id")

@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "policy_number",
        "client",
        "end_date",
        "is_provisional",
        "total_premium",
        "renewal_status",
        "assigned_agent",
    )
    list_filter = ("renewal_status", "is_provisional", "event", "assigned_agent")
    search_fields = (
        "policy_number",
        "receipt",
        "provisional_attestation",
        "brand",
        "registration",
        "client__name",
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record_audit_event(
            actor=request.user,
            action=AuditEvent.Action.CONTRACT_UPDATED,
            target=obj,
            details={"changed_fields": changed_field_names(form)},
        )
        if obj.is_terminated:
            Termination.objects.update_or_create(
                contract=obj,
                defaults={
                    "date": obj.end_date,
                    "reason": obj.event or "Résiliation",
                    "recorded_by": request.user,
                },
            )
            record_audit_event(
                actor=request.user,
                action=AuditEvent.Action.TERMINATION_RECORDED,
                target=obj,
            )
        else:
            # Une réouverture est une correction réservée à l'administrateur.
            Termination.objects.filter(contract=obj).delete()

    def delete_model(self, request, obj):
        record_audit_event(
            actor=request.user,
            action=AuditEvent.Action.CONTRACT_DELETED,
            target=obj,
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset.only("pk"):
            record_audit_event(
                actor=request.user,
                action=AuditEvent.Action.CONTRACT_DELETED,
                target=obj,
            )
        super().delete_queryset(request, queryset)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "action", "actor", "target_type", "target_id")
    list_filter = ("action", "occurred_at")
    search_fields = ("target_type", "target_id", "actor__username")
    readonly_fields = (
        "occurred_at",
        "action",
        "actor",
        "target_type",
        "target_id",
        "details",
    )
    date_hierarchy = "occurred_at"
    actions = ("export_selected_csv",)

    @admin.action(
        permissions=["view"],
        description="Exporter la sélection en CSV",
    )
    def export_selected_csv(self, request, queryset):
        total = queryset.count()
        if total > MAX_AUDIT_EXPORT_ROWS:
            self.message_user(
                request,
                f"Sélection trop grande : maximum {MAX_AUDIT_EXPORT_ROWS} lignes.",
                messages.ERROR,
            )
            return None
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="audit-{timezone.localdate():%Y-%m-%d}.csv"'
        )
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow([
            "Date",
            "Action",
            "Utilisateur",
            "Type de cible",
            "Identifiant de cible",
            "Détails",
        ])
        for event in queryset.select_related("actor").order_by(
            "-occurred_at", "-pk"
        ).iterator():
            writer.writerow([
                spreadsheet_safe(event.occurred_at.isoformat()),
                spreadsheet_safe(event.action),
                spreadsheet_safe(event.actor.username if event.actor else ""),
                spreadsheet_safe(event.target_type),
                spreadsheet_safe(event.target_id),
                spreadsheet_safe(json.dumps(
                    event.details,
                    ensure_ascii=False,
                    sort_keys=True,
                )),
            ])
        record_audit_event(
            actor=request.user,
            action=AuditEvent.Action.AUDIT_EXPORTED,
            details={"exported_count": total},
        )
        return response

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ImportBatch)
class ImportBatchAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = (
        "filename",
        "import_type",
        "imported_at",
        "imported_by",
        "added_rows",
        "updated_rows",
        "rejected_rows",
    )
    list_filter = ("import_type", "imported_at")


@admin.register(CallInteraction)
class CallInteractionAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("contract", "occurred_at", "employee", "call_result")
    list_filter = ("call_result", "occurred_at")


@admin.register(Renewal)
class RenewalAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("old_contract", "new_contract", "confirmed_by", "confirmed_at")


@admin.register(Termination)
class TerminationAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("contract", "date", "premium", "recorded_by", "created_at")
    list_filter = ("date", "created_at")
