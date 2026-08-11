"""Configuration Sentry avec minimisation explicite des données envoyées."""

from sentry_sdk import init
from sentry_sdk.integrations.django import DjangoIntegration


SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-csrftoken",
    "x-forwarded-for",
    "x-real-ip",
}


def scrub_sentry_event(event, hint):
    """Retire le corps, les cookies, la requête et l'identité nominative."""
    request = event.get("request")
    if request:
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        headers = request.get("headers") or {}
        request["headers"] = {
            key: value
            for key, value in headers.items()
            if key.lower() not in SENSITIVE_HEADERS
        }
    if event.get("user"):
        event["user"] = {"authenticated": True}
    event.pop("breadcrumbs", None)
    event.pop("extra", None)
    exception = event.get("exception") or {}
    for value in exception.get("values") or []:
        stacktrace = value.get("stacktrace") or {}
        for frame in stacktrace.get("frames") or []:
            frame.pop("vars", None)
    return event


def initialize_sentry(*, dsn, environment, traces_sample_rate):
    init(
        dsn=dsn,
        environment=environment,
        integrations=[DjangoIntegration()],
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=traces_sample_rate,
        before_send=scrub_sentry_event,
    )
