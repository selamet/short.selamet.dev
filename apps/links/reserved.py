"""Short codes the instance keeps for itself.

The admin path is environment-configurable, so it is protected by URL ordering
(the catch-all redirect route is registered last), not by this list.
"""

RESERVED_CODES = frozenset(
    {
        "admin",
        "api",
        "auth",
        "health",
        "static",
        "media",
        "w",
        "login",
        "logout",
        "signup",
        "settings",
        "support",
        "help",
        "about",
        "terms",
        "privacy",
        "security",
        "status",
        "robots",
        "favicon",
        "sitemap",
        "new",
        "edit",
        "delete",
        "links",
        "link",
        "qr",
        "short",
        "dashboard",
        "pricing",
        "blog",
        "docs",
        "app",
        "assets",
        "signin",
        "register",
        "account",
        "billing",
        "contact",
    }
)
