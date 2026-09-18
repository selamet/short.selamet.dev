"""User-agent token lists shared by apps.redirects and apps.analytics.

Lives in apps.core so neither app needs to depend on the other for these: the redirect
hot path (apps.redirects.platforms) and the click classifier (apps.analytics.useragent)
both need to know what a crawler/bot looks like, but apps.redirects.views already
imports apps.analytics.tasks (to enqueue record_click), so a module-level
apps.analytics -> apps.redirects import would be circular.
"""

CRAWLER_TOKENS = (
    "facebookexternalhit",
    "facebookcatalog",
    "twitterbot",
    "whatsapp",
    "slackbot",
    "linkedinbot",
    "telegrambot",
    "discordbot",
    "pinterest",
    "redditbot",
    "embedly",
    "skypeuripreview",
    "vkshare",
    "applebot",
    "bingpreview",
)

# Broader than CRAWLER_TOKENS: generic bot/script signatures that should be flagged as
# non-human traffic in analytics, but that the redirect path still serves a normal
# redirect to (only CRAWLER_TOKENS gets the Open Graph card instead).
#
# No bare "bot": it also matches ordinary tokens and product names that merely contain
# the letters (e.g. "robot"), flagging real browsers as bots. "bot/" (a version
# suffix, e.g. "Googlebot/2.1"), "bot " (a space-separated token) and "+bot" (a
# parenthetical contact URL, e.g. Googlebot's "(+http://www.google.com/bot.html)")
# cover real bot user agents without that false-positive risk.
BOT_TOKENS = (
    "bot/",
    "bot ",
    "+bot",
    "spider",
    "crawler",
    "curl",
    "wget",
    "python-requests",
    "headlesschrome",
)
