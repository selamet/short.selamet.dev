from django.conf import settings


def client_ip(request):
    """Client address behind TRUSTED_PROXY_HOPS reverse proxies.

    Proxies append the peer address to X-Forwarded-For, so the trustworthy entry is the
    one `hops` positions from the end; anything before it is client-supplied and ignored.
    """
    hops = settings.TRUSTED_PROXY_HOPS
    parts = [
        p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()
    ]
    if hops and len(parts) >= hops:
        return parts[-hops]
    return request.META.get("REMOTE_ADDR", "")
