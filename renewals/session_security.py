from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone
from django.utils.cache import patch_cache_control


SESSION_DAY_KEY = "_renewal_login_day"


def discard_client_ip(request):
    """Avoid storing staff IP addresses in authentication-attempt records."""
    return None


def current_local_day():
    """Return the agency's current calendar day."""
    return timezone.localdate()


def next_local_midnight():
    """Return the next midnight in the active Django timezone."""
    tomorrow = current_local_day() + timedelta(days=1)
    return timezone.make_aware(
        datetime.combine(tomorrow, time.min),
        timezone.get_current_timezone(),
    )


@receiver(user_logged_in)
def expire_session_at_midnight(sender, request, user, **kwargs):
    """Make every new login expire at the next Moroccan midnight."""
    if request is None:
        return
    request.session[SESSION_DAY_KEY] = current_local_day().isoformat()
    request.session.set_expiry(next_local_midnight())


class LogoutAfterMidnightMiddleware:
    """Reject an authenticated session as soon as its login day has ended."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            login_day = request.session.get(SESSION_DAY_KEY)
            if login_day != current_local_day().isoformat():
                logout(request)
        return self.get_response(request)


class ApplicationSecurityHeadersMiddleware:
    """Apply a CSP and prevent authenticated pages from being cached."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        is_admin = request.path.startswith("/admin/")
        script_source = (
            "script-src 'self' 'unsafe-inline'"
            if is_admin
            else "script-src 'self'"
        )
        style_source = (
            "style-src 'self' 'unsafe-inline'"
            if is_admin
            else "style-src 'self' https://fonts.googleapis.com"
        )
        directives = [
            "default-src 'self'",
            script_source,
            style_source,
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
        if not settings.DEBUG:
            directives.append("upgrade-insecure-requests")
        response.headers.setdefault(
            "Content-Security-Policy",
            "; ".join(directives),
        )
        if request.user.is_authenticated:
            patch_cache_control(
                response,
                private=True,
                no_cache=True,
                no_store=True,
                must_revalidate=True,
                max_age=0,
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


def session_security_context(request):
    """Expose the server-side expiry so an idle browser also leaves the app."""
    if not request.user.is_authenticated:
        return {}
    return {"session_expiry_iso": request.session.get_expiry_date().isoformat()}
