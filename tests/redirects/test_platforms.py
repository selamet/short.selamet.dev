import pytest

from apps.redirects import platforms
from tests.redirects.conftest import ANDROID_UA, DESKTOP_UA, IOS_UA


@pytest.mark.parametrize(
    "user_agent,expected",
    [
        (IOS_UA, "ios"),
        ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)", "ios"),
        (ANDROID_UA, "android"),
        (DESKTOP_UA, "desktop"),
        ("", "desktop"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "desktop"),
    ],
)
def test_detect_platform(user_agent, expected):
    assert platforms.detect_platform(user_agent) == expected


@pytest.mark.parametrize(
    "user_agent",
    [
        "facebookexternalhit/1.1",
        "Twitterbot/1.0",
        "WhatsApp/2.23",
        "Slackbot-LinkExpanding 1.0",
        "LinkedInBot/1.0",
        "TelegramBot (like TwitterBot)",
        "Discordbot/2.0",
    ],
)
def test_is_crawler(user_agent):
    assert platforms.is_crawler(user_agent) is True


def test_normal_browsers_are_not_crawlers():
    assert platforms.is_crawler(IOS_UA) is False
    assert platforms.is_crawler(DESKTOP_UA) is False
