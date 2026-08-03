from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Client, Contract, ImportBatch, CallInteraction, Renewal, Termination

@admin.register(User)
class AgencyUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Agence", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Agence", {"fields": ("role",)}),)
    list_display = ("username", "first_name", "last_name", "role", "is_active")

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
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
        if obj.is_terminated:
            Termination.objects.update_or_create(
                contract=obj,
                defaults={
                    "date": obj.end_date,
                    "reason": obj.event or "Résiliation",
                    "recorded_by": request.user,
                },
            )
        else:
            # Une réouverture est une correction réservée à l'administrateur.
            Termination.objects.filter(contract=obj).delete()

admin.site.register([ImportBatch, CallInteraction, Renewal, Termination])
