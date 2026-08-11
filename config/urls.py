from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.urls import include, path

from renewals.auth_views import (
    AgencyLoginView,
    AgencyPasswordChangeView,
    mfa_setup,
    mfa_verify,
)


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path("connexion/", AgencyLoginView.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("mot-de-passe/", AgencyPasswordChangeView.as_view(), name="password_change"),
    path("securite/mfa/configurer/", mfa_setup, name="mfa_setup"),
    path("securite/mfa/verifier/", mfa_verify, name="mfa_verify"),
    path("", include("renewals.urls")),
]
