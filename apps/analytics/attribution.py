"""Referrer and UTM extraction shared by the redirect view and the click task.

Called from the view, before the click is enqueued: the production task backend
persists its arguments to the database, so the raw referrer (which can carry
credentials in its userinfo) and the raw query string must never be handed to
`record_click.enqueue()` in the first place. Splitting this out of `apps.analytics.tasks`
lets `apps.redirects.views` reuse the exact same parsing without importing the task
module's internals.
"""

from urllib.parse import parse_qs, urlsplit, urlunsplit

UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def split_referrer(referrer):
    """The referrer's host and a credential-and-query-and-fragment-free URL, or
    `("", "")` when there is no referrer to parse.

    Built from `hostname`/`port`, not `netloc`, so any userinfo (`user:pass@`) in the
    original URL is dropped along with the query string and fragment rather than
    ending up stored.
    """
    if not referrer:
        return "", ""
    parts = urlsplit(referrer)
    host = parts.hostname or ""
    if not host:
        return "", ""
    netloc = f"[{host}]" if ":" in host else host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    clean_url = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return host, clean_url


def utm_from_query_string(query_string):
    params = parse_qs(query_string or "")
    return {field: (params.get(field) or [""])[0] for field in UTM_FIELDS}
