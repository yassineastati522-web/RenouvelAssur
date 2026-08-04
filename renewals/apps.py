from django.apps import AppConfig

class RenewalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "renewals"
    verbose_name = "Renouvellements"

    def ready(self):
        # Register the login signal that limits every session to one agency day.
        from . import session_security  # noqa: F401
