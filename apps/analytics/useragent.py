"""User agent classification for click analytics.

Deliberately a small table of substring checks rather than a parsing library: it is
honest about what it can tell (mobile vs. tablet vs. desktop, a handful of named
operating systems and browsers, and a bot flag), fast enough to run on every click, and
easy for the analytics issue to swap for a real parser later without touching the task
that calls it.
"""

from apps.core.useragents import BOT_TOKENS, CRAWLER_TOKENS

MOBILE_TOKENS = ("iphone", "ipod", "android", "mobile", "windows phone")
TABLET_TOKENS = ("ipad", "tablet", "kindle", "silk")

# Checked in order, first match wins.
OS_TOKENS = (
    ("windows", "Windows"),
    ("iphone", "iOS"),
    ("ipad", "iOS"),
    ("ipod", "iOS"),
    ("mac os x", "macOS"),
    ("android", "Android"),
    ("cros", "ChromeOS"),
    ("linux", "Linux"),
)

# Checked in order, first match wins: Edge/Opera/headless Chrome and the *iOS wrapper
# tokens all contain "chrome"/"safari" too, so the more specific tokens are listed first.
BROWSER_TOKENS = (
    ("edg/", "Edge"),
    ("opr/", "Opera"),
    ("headlesschrome", "Headless Chrome"),
    ("crios", "Chrome"),
    ("fxios", "Firefox"),
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("safari", "Safari"),
    ("curl", "curl"),
    ("wget", "Wget"),
    ("python-requests", "python-requests"),
)


def device_type(user_agent):
    agent = (user_agent or "").lower()
    if any(token in agent for token in TABLET_TOKENS):
        return "tablet"
    if any(token in agent for token in MOBILE_TOKENS):
        return "mobile"
    return "desktop"


def operating_system(user_agent):
    agent = (user_agent or "").lower()
    for token, name in OS_TOKENS:
        if token in agent:
            return name
    return ""


def browser(user_agent):
    agent = (user_agent or "").lower()
    for token, name in BROWSER_TOKENS:
        if token in agent:
            return name
    return ""


def is_bot(user_agent):
    agent = (user_agent or "").lower()
    return any(token in agent for token in (*CRAWLER_TOKENS, *BOT_TOKENS))
