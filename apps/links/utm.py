"""Platform UTM presets and merging."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")

UTM_PRESETS = {
    "instagram-bio": {
        "label": "Instagram bio",
        "params": {"utm_source": "instagram", "utm_medium": "bio"},
    },
    "instagram-story": {
        "label": "Instagram story",
        "params": {"utm_source": "instagram", "utm_medium": "story"},
    },
    "tiktok-profile": {
        "label": "TikTok profile",
        "params": {"utm_source": "tiktok", "utm_medium": "profile"},
    },
    "youtube-description": {
        "label": "YouTube description",
        "params": {"utm_source": "youtube", "utm_medium": "description"},
    },
    "newsletter": {
        "label": "Newsletter",
        "params": {"utm_source": "newsletter", "utm_medium": "email"},
    },
}


def apply_preset(key, campaign=""):
    preset = UTM_PRESETS.get(key)
    if preset is None:
        return {}
    params = dict(preset["params"])
    if campaign:
        params["utm_campaign"] = campaign
    return params


def merge_utm(url, params):
    """Add the non-empty params the destination does not already carry."""
    additions = {key: value for key, value in (params or {}).items() if value}
    if not additions:
        return url
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    existing = {key for key, _ in query}
    query.extend((key, value) for key, value in additions.items() if key not in existing)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
