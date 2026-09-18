"""User agent classification for the redirect hot path.

Deliberately a handful of substring checks rather than a parsing library: this runs on
every click, and the only decisions are iOS versus Android versus everything else, plus
whether the caller is a social crawler that wants a card instead of a redirect.
"""

from apps.core.useragents import CRAWLER_TOKENS

IOS_TOKENS = ("iphone", "ipad", "ipod")


def detect_platform(user_agent):
    agent = (user_agent or "").lower()
    if any(token in agent for token in IOS_TOKENS):
        return "ios"
    if "android" in agent:
        return "android"
    return "desktop"


def is_crawler(user_agent):
    agent = (user_agent or "").lower()
    return any(token in agent for token in CRAWLER_TOKENS)
