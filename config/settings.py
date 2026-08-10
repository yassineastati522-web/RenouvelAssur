import os
import urllib.parse
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
IS_HOSTED = bool(os.environ.get("VERCEL") or os.environ.get("RENDER"))
DEBUG = os.environ.get(
    "DJANGO_DEBUG", "0" if IS_HOSTED else "1"
) == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-change-me"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY doit être définie lorsque DJANGO_DEBUG=0."
        )
ALLOWED_HOSTS = [h.strip() for h in os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1"
).split(",") if h.strip()]

for hostname in (
    os.environ.get("RENDER_EXTERNAL_HOSTNAME"),
    os.environ.get("VERCEL_URL"),
):
    if hostname and hostname not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(hostname)

CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get(
    "DJANGO_CSRF_TRUSTED_ORIGINS", ""
).split(",") if origin.strip()]
for hostname in (
    os.environ.get("RENDER_EXTERNAL_HOSTNAME"),
    os.environ.get("VERCEL_URL"),
):
    origin = f"https://{hostname}" if hostname else ""
    if origin and origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "axes",
    "renewals",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "renewals.session_security.LogoutAfterMidnightMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=30)
AXES_LOCKOUT_PARAMETERS = ["username"]
AXES_CLIENT_IP_CALLABLE = "renewals.session_security.discard_client_ip"
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/lockout.html"
AXES_HTTP_RESPONSE_CODE = 429
AXES_ENABLED = os.environ.get(
    "DJANGO_AXES_ENABLED", "1" if not DEBUG else "0"
) == "1"
# Username-only tracking is intentional: it avoids retaining staff IP addresses.
SILENCED_SYSTEM_CHECKS = ["axes.W006"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "renewals.session_security.session_security_context",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("DATABASE_URL"):
    database_url = urllib.parse.urlparse(os.environ["DATABASE_URL"])
    database_options = {
        key: values[-1]
        for key, values in urllib.parse.parse_qs(
            database_url.query, keep_blank_values=True
        ).items()
    }
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database_url.path.lstrip("/"),
        "USER": urllib.parse.unquote(database_url.username or ""),
        "PASSWORD": urllib.parse.unquote(database_url.password or ""),
        "HOST": database_url.hostname or "",
        "PORT": database_url.port or "5432",
        "CONN_MAX_AGE": int(os.environ.get("DATABASE_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": database_options,
    }}
elif os.environ.get("POSTGRES_DB"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", "postgres"), "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"), "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.environ.get("DATABASE_CONN_MAX_AGE", "60")), "CONN_HEALTH_CHECKS": True}}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Casablanca"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "renewals.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

SECURE_SSL_REDIRECT = os.environ.get(
    "DJANGO_SECURE_SSL_REDIRECT", "1" if not DEBUG else "0"
) == "1"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = int(os.environ.get(
    "DJANGO_SECURE_HSTS_SECONDS", "3600" if not DEBUG else "0"
))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "0"
) == "1"
SECURE_HSTS_PRELOAD = os.environ.get(
    "DJANGO_SECURE_HSTS_PRELOAD", "0"
) == "1"

TERMINATION_EVENTS = [v.strip() for v in os.environ.get(
    "TERMINATION_EVENTS", "Résiliation,Annulation,Avenant de résiliation,Ristourne"
).split(",") if v.strip()]
