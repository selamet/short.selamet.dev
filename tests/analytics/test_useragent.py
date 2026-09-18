from apps.analytics import useragent
from tests.redirects.conftest import ANDROID_UA, DESKTOP_UA, IOS_UA


def test_ordinary_browsers_are_not_flagged_as_bots():
    assert useragent.is_bot(DESKTOP_UA) is False
    assert useragent.is_bot(IOS_UA) is False
    assert useragent.is_bot(ANDROID_UA) is False


def test_googlebot_is_flagged_via_the_versioned_bot_token():
    assert useragent.is_bot("Googlebot/2.1 (+http://www.google.com/bot.html)") is True
