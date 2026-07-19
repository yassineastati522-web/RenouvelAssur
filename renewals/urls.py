from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("contrats/", views.contract_list, name="contract_list"),
    path("contrats/non-renouveles/", views.expired_list, name="expired_list"),
    path("contrats/resilies/", views.terminated_list, name="terminated_list"),
    path("appels/", views.call_checklist, name="call_checklist"),
    path("contrats/<int:pk>/", views.contract_detail, name="contract_detail"),
    path("contrats/<int:pk>/supprimer/", views.contract_delete, name="contract_delete"),
    path("clients/", views.client_list, name="client_list"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),
    path("imports/", views.import_view, name="import_view"),
    path("imports/<int:pk>/", views.import_report, name="import_report"),
]
