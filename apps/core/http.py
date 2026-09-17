def client_ip(request):
    """Best-effort client address behind the reverse proxy (first X-Forwarded-For hop)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
