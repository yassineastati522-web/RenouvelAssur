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
    list_display = ("policy_number", "client", "end_date", "total_premium", "renewal_status", "assigned_agent")
    list_filter = ("renewal_status", "event", "assigned_agent")
    search_fields = ("policy_number", "receipt", "brand", "registration", "client__name")

admin.site.register([ImportBatch, CallInteraction, Renewal, Termination])
