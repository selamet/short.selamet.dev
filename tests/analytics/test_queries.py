"""Tests for apps.analytics.queries: the read-only functions the dashboard uses.

Builds one small, fixed dataset (two workspaces, three links, several days) directly
against the rollup tables -- DailyLinkStat and DailyLinkBreakdown are seeded straight
via the ORM rather than through apps.analytics.rollups, since rollups' own
correctness is already covered by tests/analytics/test_rollups.py and this file only
needs to prove queries.py reads them right. recent_clicks and hour_weekday_matrix are
the two exceptions that read raw ClickEvent rows, so they get their own events.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.utils import timezone

from apps.analytics import attribution, queries
from apps.analytics.models import (
    ClickEvent,
    DailyClickIdentity,
    DailyLinkBreakdown,
    DailyLinkStat,
    Dimension,
)
from apps.analytics.tasks import record_click
from apps.core.privacy import hash_ip
from apps.links import services as link_services
from apps.links.models import Link
from apps.workspaces import services as workspace_services
from apps.workspaces.models import Membership, Role
from tests.redirects.conftest import DESKTOP_UA

BOT_UA = "Googlebot/2.1 (+http://www.google.com/bot.html)"

PREVIOUS_START = date(2026, 2, 7)
PREVIOUS_END = date(2026, 2, 9)
START = date(2026, 2, 10)
END = date(2026, 2, 12)
MATRIX_START = date(2026, 3, 2)  # a Monday
MATRIX_END = date(2026, 3, 8)  # the following Sunday


def _membership(owner, slug, timezone_name="UTC"):
    workspace = workspace_services.create_workspace(owner, name=slug, slug=slug)
    if timezone_name != "UTC":
        workspace.timezone = timezone_name
        workspace.save(update_fields=["timezone"])
    return Membership.objects.get(workspace=workspace, user=owner, role=Role.OWNER)


def _stat(link, day, clicks, unique_clicks, bot_clicks=0):
    DailyLinkStat.objects.create(
        link=link,
        workspace=link.workspace,
        date=day,
        clicks=clicks,
        unique_clicks=unique_clicks,
        bot_clicks=bot_clicks,
    )


def _identity(link, day, identity):
    DailyClickIdentity.objects.create(
        link=link, workspace=link.workspace, date=day, identity=identity
    )


def _breakdown(link, day, value, clicks, dimension=Dimension.COUNTRY, bot_clicks=0):
    DailyLinkBreakdown.objects.create(
        link=link,
        workspace=link.workspace,
        date=day,
        dimension=dimension,
        value=value,
        clicks=clicks,
        bot_clicks=bot_clicks,
    )


def _click(link, **overrides):
    """Records one click through record_click, the same task the redirect view
    enqueues, rather than seeding the rollup tables directly: used by the tests below
    that need query semantics to stay bound to whatever the write path (and
    apps.analytics.rollups) actually produces."""
    payload = {
        "occurred_at": timezone.now().isoformat(),
        "ip_hash": hash_ip("203.0.113.1"),
        "user_agent": DESKTOP_UA,
        "referrer_host": "",
        "referrer_url": "",
        "target_platform": "desktop",
        "country": "",
        "city": "",
        **attribution.utm_from_query_string(""),
    }
    payload.update(overrides)
    record_click.enqueue(link.pk, **payload)


def _event(link, occurred_at, **overrides):
    defaults = {
        "link": link,
        "workspace": link.workspace,
        "occurred_at": occurred_at,
        "ip_hash": "hash",
        "user_agent": DESKTOP_UA,
        "is_bot": False,
    }
    defaults.update(overrides)
    return ClickEvent.objects.create(**defaults)


@pytest.fixture
def dataset(owner):
    membership_a = _membership(owner, "workspace-a", timezone_name="Europe/Istanbul")
    membership_b = _membership(owner, "workspace-b")
    link_a = link_services.create_link(
        membership_a, destination_url="https://example.com/a", code="link-a"
    )
    link_a2 = link_services.create_link(
        membership_a, destination_url="https://example.com/a2", code="link-a2"
    )
    link_b = link_services.create_link(
        membership_b, destination_url="https://example.com/b", code="link-b"
    )
    Link.objects.filter(pk=link_a.pk).update(title="Alpha")
    Link.objects.filter(pk=link_a2.pk).update(title="Alpha Two")

    # Previous period (the delta baseline) -- link_a only. PREVIOUS_END deliberately
    # gets no row, to prove Sum() over a gap behaves like zero.
    _stat(link_a, PREVIOUS_START, clicks=10, unique_clicks=8, bot_clicks=2)
    _stat(link_a, PREVIOUS_START + timedelta(days=1), clicks=5, unique_clicks=4, bot_clicks=1)

    # Current period -- link_a. START+1 (Feb 11) deliberately gets no row, to prove
    # time_series() fills the gap with zero.
    _stat(link_a, START, clicks=14, unique_clicks=10, bot_clicks=3)
    _stat(link_a, END, clicks=7, unique_clicks=7, bot_clicks=0)

    # Current period -- link_a2, a second link in the same workspace (leaderboard,
    # and breakdown()'s link=None workspace-wide aggregation, need more than one).
    _stat(link_a2, START, clicks=6, unique_clicks=5, bot_clicks=1)
    _stat(link_a2, START + timedelta(days=1), clicks=3, unique_clicks=2, bot_clicks=0)

    # Another workspace's data, on the very same dates: every function under test
    # must ignore this, however it is called.
    _stat(link_b, START, clicks=99999, unique_clicks=99999, bot_clicks=0)

    _breakdown(link_a, START, "US", 6)
    _breakdown(link_a, END, "US", 4)
    _breakdown(link_a, START, "TR", 6)
    _breakdown(link_a2, START + timedelta(days=1), "DE", 4)
    _breakdown(link_b, START, "US", 99999)

    # I3: DailyClickIdentity backs summary()'s workspace-wide unique_clicks.
    # visitor-1 clicks two different links on two different days -- must still count
    # once for the workspace, not once per link/day the way summing DailyLinkStat
    # .unique_clicks across links and days would.
    _identity(link_a, START, "visitor-1")
    _identity(link_a2, START + timedelta(days=1), "visitor-1")
    _identity(link_a, START, "visitor-2")
    _identity(link_a, END, "visitor-3")
    # Another workspace's identity: must never be counted for workspace_a.
    _identity(link_b, START, "visitor-1")

    return SimpleNamespace(
        workspace_a=membership_a.workspace,
        workspace_b=membership_b.workspace,
        link_a=link_a,
        link_a2=link_a2,
        link_b=link_b,
    )


# --- summary --------------------------------------------------------------------------


@pytest.mark.django_db
def test_summary_excludes_bots_by_default_and_computes_the_delta(dataset):
    result = queries.summary(dataset.workspace_a, dataset.link_a, start=START, end=END)
    assert result == {
        "clicks": 18,
        "unique_clicks": 17,
        "bot_clicks": 3,
        "previous_clicks": 12,
        "delta_pct": 50.0,
    }


@pytest.mark.django_db
def test_summary_include_bots_folds_bot_clicks_back_into_the_totals(dataset):
    result = queries.summary(
        dataset.workspace_a, dataset.link_a, start=START, end=END, include_bots=True
    )
    assert (result["clicks"], result["previous_clicks"], result["delta_pct"]) == (21, 15, 40.0)


@pytest.mark.django_db
def test_summary_link_none_aggregates_the_whole_workspace_and_ignores_other_workspaces(dataset):
    result = queries.summary(dataset.workspace_a, start=START, end=END)
    assert result == {
        "clicks": 26,  # link_a (18) + link_a2 (6-1 + 3-0 = 8)
        # I3: distinct DailyClickIdentity rows for workspace_a in range, not a sum of
        # per-link unique_clicks -- visitor-1 clicked two links but counts once.
        "unique_clicks": 3,  # visitor-1, visitor-2, visitor-3
        "bot_clicks": 4,  # 3 + 1
        "previous_clicks": 12,  # link_a2 has no rows in the previous period
        "delta_pct": 116.7,
    }


@pytest.mark.django_db
def test_summary_with_no_previous_clicks_reports_none_or_zero_delta(dataset):
    no_previous = queries.summary(
        dataset.workspace_a, dataset.link_a, start=END, end=END
    )  # a range with clicks but nothing before PREVIOUS_START in this dataset either
    assert no_previous["previous_clicks"] == 0
    assert no_previous["delta_pct"] is None

    truly_empty = queries.summary(
        dataset.workspace_a, dataset.link_a, start=date(2020, 1, 1), end=date(2020, 1, 1)
    )
    assert truly_empty == {
        "clicks": 0,
        "unique_clicks": 0,
        "bot_clicks": 0,
        "previous_clicks": 0,
        "delta_pct": 0.0,
    }


@pytest.mark.django_db
def test_workspace_unique_clicks_counts_distinct_visitors_not_a_sum_of_per_link_uniques(owner):
    """I3: one visitor clicking two links in a workspace is two clicks and one unique
    visitor at the workspace level (not two), and one unique click per link. Goes
    through record_click (not seeded rollup rows) so query semantics stay bound to
    what rollups.apply_event actually produces.
    """
    membership = _membership(owner, "unique-workspace")
    link_a = link_services.create_link(
        membership, destination_url="https://example.com/uw-a", code="uw-link-a"
    )
    link_b = link_services.create_link(
        membership, destination_url="https://example.com/uw-b", code="uw-link-b"
    )
    same_visitor = hash_ip("203.0.113.99")
    today = timezone.localdate()
    _click(link_a, ip_hash=same_visitor)
    _click(link_b, ip_hash=same_visitor)

    workspace_summary = queries.summary(membership.workspace, start=today, end=today)
    assert workspace_summary["clicks"] == 2
    assert workspace_summary["unique_clicks"] == 1

    per_link_a = queries.summary(membership.workspace, link_a, start=today, end=today)
    per_link_b = queries.summary(membership.workspace, link_b, start=today, end=today)
    assert per_link_a["unique_clicks"] == 1
    assert per_link_b["unique_clicks"] == 1


# --- time_series ----------------------------------------------------------------------


@pytest.mark.django_db
def test_time_series_fills_gaps_with_zero_and_excludes_bots(dataset):
    points = queries.time_series(dataset.workspace_a, dataset.link_a, start=START, end=END)
    assert points == [
        {"date": START, "clicks": 11, "unique_clicks": 10},
        {"date": START + timedelta(days=1), "clicks": 0, "unique_clicks": 0},
        {"date": END, "clicks": 7, "unique_clicks": 7},
    ]


@pytest.mark.django_db
def test_time_series_rejects_an_unsupported_granularity(dataset):
    with pytest.raises(ValueError):
        queries.time_series(
            dataset.workspace_a, dataset.link_a, start=START, end=END, granularity="month"
        )


@pytest.mark.django_db
def test_time_series_include_bots_folds_bot_clicks_back_in(dataset):
    points = queries.time_series(
        dataset.workspace_a, dataset.link_a, start=START, end=END, include_bots=True
    )
    assert points == [
        {"date": START, "clicks": 14, "unique_clicks": 10},
        {"date": START + timedelta(days=1), "clicks": 0, "unique_clicks": 0},
        {"date": END, "clicks": 7, "unique_clicks": 7},
    ]


@pytest.mark.django_db
def test_time_series_and_summary_agree_over_the_same_window(dataset):
    # I2: same arithmetic, same default -- summing the daily series must reproduce
    # summary()'s own totals for the identical window.
    points = queries.time_series(dataset.workspace_a, dataset.link_a, start=START, end=END)
    summary = queries.summary(dataset.workspace_a, dataset.link_a, start=START, end=END)
    assert sum(point["clicks"] for point in points) == summary["clicks"]
    assert sum(point["unique_clicks"] for point in points) == summary["unique_clicks"]


# --- breakdown ------------------------------------------------------------------------


@pytest.mark.django_db
def test_breakdown_orders_by_clicks_and_shares_against_this_links_own_total(dataset):
    rows = queries.breakdown(
        dataset.workspace_a, Dimension.COUNTRY, link=dataset.link_a, start=START, end=END
    )
    assert rows == [
        {"value": "US", "clicks": 10, "share": 62.5},
        {"value": "TR", "clicks": 6, "share": 37.5},
    ]


@pytest.mark.django_db
def test_breakdown_link_none_aggregates_the_workspace_and_ignores_other_workspaces(dataset):
    rows = queries.breakdown(dataset.workspace_a, Dimension.COUNTRY, start=START, end=END)
    assert rows == [
        {"value": "US", "clicks": 10, "share": 50.0},
        {"value": "TR", "clicks": 6, "share": 30.0},
        {"value": "DE", "clicks": 4, "share": 20.0},
    ]


@pytest.mark.django_db
def test_breakdown_limit_truncates_the_list_but_shares_stay_against_the_full_total(dataset):
    rows = queries.breakdown(dataset.workspace_a, Dimension.COUNTRY, start=START, end=END, limit=2)
    assert rows == [
        {"value": "US", "clicks": 10, "share": 50.0},
        {"value": "TR", "clicks": 6, "share": 30.0},
    ]


@pytest.mark.django_db
def test_breakdown_excludes_bots_by_default_and_include_bots_folds_them_back_in(link):
    # I1: breakdown() used to include bot clicks unconditionally, disagreeing with
    # summary()'s default -- a dashboard's total and its own breakdown could
    # therefore never add up.
    today = timezone.localdate()
    _breakdown(link, today, "US", clicks=10, bot_clicks=4)
    _breakdown(link, today, "TR", clicks=6, bot_clicks=0)

    rows = queries.breakdown(link.workspace, Dimension.COUNTRY, link=link, start=today, end=today)
    # US and TR tie at 6 net clicks each once US's bots are subtracted; the query's
    # own tie-break (ORDER BY -clicks, value) then puts them in ascending value order.
    assert rows == [
        {"value": "TR", "clicks": 6, "share": 50.0},
        {"value": "US", "clicks": 6, "share": 50.0},
    ]

    rows_with_bots = queries.breakdown(
        link.workspace, Dimension.COUNTRY, link=link, start=today, end=today, include_bots=True
    )
    assert rows_with_bots == [
        {"value": "US", "clicks": 10, "share": 62.5},
        {"value": "TR", "clicks": 6, "share": 37.5},
    ]


@pytest.mark.django_db
def test_summary_breakdown_and_leaderboard_agree_on_bot_clicks(owner):
    """I1: summary() already excluded bot clicks by default; breakdown() and
    leaderboard() did not, so a dashboard's headline total could disagree with its
    own breakdown or leaderboard for the exact same range. Goes through record_click
    (not seeded rollup rows) so this stays bound to what the write path actually
    produces, not to a hand-built fixture that merely resembles it.
    """
    membership = _membership(owner, "bot-consistency")
    link = link_services.create_link(
        membership, destination_url="https://example.com/bots", code="bot-link"
    )
    today = timezone.localdate()
    _click(link, ip_hash=hash_ip("203.0.113.10"), country="US")
    _click(link, ip_hash=hash_ip("203.0.113.11"), country="TR")
    _click(link, ip_hash=hash_ip("203.0.113.12"), country="US", user_agent=BOT_UA)

    summary = queries.summary(membership.workspace, link, start=today, end=today)
    breakdown_rows = queries.breakdown(
        membership.workspace, Dimension.COUNTRY, link, start=today, end=today
    )
    leaderboard_rows = queries.leaderboard(membership.workspace, today, today)

    assert summary["clicks"] == 2
    assert sum(row["clicks"] for row in breakdown_rows) == summary["clicks"]
    assert leaderboard_rows == [{"code": "bot-link", "title": "", "clicks": 2}]

    summary_with_bots = queries.summary(
        membership.workspace, link, start=today, end=today, include_bots=True
    )
    breakdown_with_bots = queries.breakdown(
        membership.workspace, Dimension.COUNTRY, link, start=today, end=today, include_bots=True
    )
    leaderboard_with_bots = queries.leaderboard(
        membership.workspace, today, today, include_bots=True
    )
    assert summary_with_bots["clicks"] == 3
    assert sum(row["clicks"] for row in breakdown_with_bots) == summary_with_bots["clicks"]
    assert leaderboard_with_bots == [{"code": "bot-link", "title": "", "clicks": 3}]


@pytest.mark.django_db
def test_breakdown_limit_is_clamped_to_the_configured_maximum(dataset, settings):
    settings.ANALYTICS_QUERY_MAX_LIMIT = 1
    rows = queries.breakdown(
        dataset.workspace_a, Dimension.COUNTRY, start=START, end=END, limit=100
    )
    assert len(rows) == 1


# --- leaderboard ----------------------------------------------------------------------


@pytest.mark.django_db
def test_leaderboard_orders_links_by_clicks_and_ignores_other_workspaces(dataset):
    rows = queries.leaderboard(dataset.workspace_a, START, END)
    assert rows == [
        {"code": "link-a", "title": "Alpha", "clicks": 18},  # 21 raw - 3 bots
        {"code": "link-a2", "title": "Alpha Two", "clicks": 8},  # 9 raw - 1 bot
    ]


@pytest.mark.django_db
def test_leaderboard_limit(dataset):
    rows = queries.leaderboard(dataset.workspace_a, START, END, limit=1)
    assert rows == [{"code": "link-a", "title": "Alpha", "clicks": 18}]


@pytest.mark.django_db
def test_leaderboard_include_bots_folds_bot_clicks_back_in(dataset):
    # I1: leaderboard() used to include bot clicks unconditionally, the same
    # inconsistency breakdown() had.
    rows = queries.leaderboard(dataset.workspace_a, START, END, include_bots=True)
    assert rows == [
        {"code": "link-a", "title": "Alpha", "clicks": 21},
        {"code": "link-a2", "title": "Alpha Two", "clicks": 9},
    ]


@pytest.mark.django_db
def test_leaderboard_skips_a_link_deleted_between_the_aggregate_and_the_fetch(dataset, monkeypatch):
    from django.db.models.query import QuerySet

    original_in_bulk = QuerySet.in_bulk

    def in_bulk_after_deleting_link_a2(self, *args, **kwargs):
        # Simulates dataset.link_a2 being deleted in the gap between leaderboard()'s
        # aggregate query and its Link.objects.in_bulk() lookup.
        Link.objects.filter(pk=dataset.link_a2.pk).delete()
        return original_in_bulk(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "in_bulk", in_bulk_after_deleting_link_a2)

    rows = queries.leaderboard(dataset.workspace_a, START, END)

    assert rows == [{"code": "link-a", "title": "Alpha", "clicks": 18}]


@pytest.mark.django_db
def test_leaderboard_breaks_ties_by_ascending_link_id(owner):
    # Two links with equal clicks: the query's own tie-break (ORDER BY -clicks,
    # link_id) puts the lower-pk link first. first_link is created before
    # second_link, so it has the lower pk; the returned order must match the
    # query's, not Link's own default ordering (-created_at), which would put
    # second_link first if the two were ever independently re-sorted in Python.
    membership = _membership(owner, "tie-workspace")
    first_link = link_services.create_link(
        membership, destination_url="https://example.com/first", code="first-link"
    )
    second_link = link_services.create_link(
        membership, destination_url="https://example.com/second", code="second-link"
    )
    _stat(first_link, START, clicks=5, unique_clicks=5, bot_clicks=0)
    _stat(second_link, START, clicks=5, unique_clicks=5, bot_clicks=0)

    rows = queries.leaderboard(membership.workspace, START, END)

    assert [row["code"] for row in rows] == ["first-link", "second-link"]


# --- recent_clicks --------------------------------------------------------------------


@pytest.mark.django_db
def test_recent_clicks_reads_raw_events_newest_first_and_respects_retention(dataset):
    now = timezone.now()
    old = now - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS + 1)
    _event(dataset.link_a, occurred_at=old, country="FR", city="Paris")
    _event(dataset.link_a, occurred_at=now - timedelta(hours=3), country="DE", city="Berlin")
    _event(dataset.link_a, occurred_at=now - timedelta(hours=2), country="TR", city="Istanbul")
    _event(dataset.link_a, occurred_at=now - timedelta(hours=1), country="US", city="Reno")

    rows = queries.recent_clicks(dataset.workspace_a, dataset.link_a, limit=20)

    assert [row["country"] for row in rows] == ["US", "TR", "DE"]
    assert rows[0] == {
        "occurred_at": rows[0]["occurred_at"],
        "country": "US",
        "city": "Reno",
        "device_type": "",
        "browser": "",
        "referrer_host": "",
        "target_platform": "",
    }


@pytest.mark.django_db
def test_recent_clicks_limit_and_workspace_link_mismatch(dataset):
    now = timezone.now()
    _event(dataset.link_a, occurred_at=now - timedelta(hours=1))
    _event(dataset.link_a, occurred_at=now - timedelta(hours=2))

    assert len(queries.recent_clicks(dataset.workspace_a, dataset.link_a, limit=1)) == 1
    # link_a actually belongs to workspace_a; asking under workspace_b must yield
    # nothing, even though link_a itself is a perfectly valid link.
    assert queries.recent_clicks(dataset.workspace_b, dataset.link_a, limit=20) == []


# --- hour_weekday_matrix ----------------------------------------------------------------


@pytest.mark.django_db
def test_hour_weekday_matrix_shape_and_a_known_peak(dataset, settings):
    # Fixed 2026-03 dates, chosen for their known weekday/hour shape, are long past a
    # realistic CLICK_EVENT_RETENTION_DAYS by the time this runs; widen it here so the
    # retention floor added below does not clip this fixture's events (see the
    # dedicated retention-floor test for that behavior instead).
    settings.CLICK_EVENT_RETENTION_DAYS = 36500
    # Workspace A is Europe/Istanbul (UTC+3, no DST): times below are chosen so their
    # local hour/weekday differs from their UTC one, proving the conversion actually
    # happens rather than just reading occurred_at's own UTC fields.
    for _ in range(4):
        # Mon 09:00 local.
        _event(dataset.link_a, occurred_at=datetime(2026, 3, 2, 6, 0, tzinfo=UTC))
    _event(dataset.link_a, occurred_at=datetime(2026, 3, 4, 11, 0, tzinfo=UTC))  # Wed 14:00 local
    # UTC date is Mar 1 (before MATRIX_START); local date is Mar 2 -- must still count.
    _event(dataset.link_a, occurred_at=datetime(2026, 3, 1, 22, 0, tzinfo=UTC))  # Mon 01:00 local
    # Local date is Mar 9 (after MATRIX_END) -- must be excluded even though it is
    # inside the padded UTC scan window.
    _event(dataset.link_a, occurred_at=datetime(2026, 3, 8, 22, 0, tzinfo=UTC))
    # A bot click, excluded by default (see the include_bots test below).
    _event(
        dataset.link_a,
        occurred_at=datetime(2026, 3, 2, 6, 0, tzinfo=UTC),
        is_bot=True,
        user_agent=BOT_UA,
    )

    matrix = queries.hour_weekday_matrix(
        dataset.workspace_a, dataset.link_a, MATRIX_START, MATRIX_END
    )

    assert len(matrix) == 7
    assert all(len(row) == 24 for row in matrix)
    assert matrix[0][9] == 4  # the known peak: Monday, 09:00 local
    assert matrix[0][1] == 1
    assert matrix[2][14] == 1
    assert sum(sum(row) for row in matrix) == 6


@pytest.mark.django_db
def test_hour_weekday_matrix_include_bots_counts_the_bot_click_too(dataset, settings):
    settings.CLICK_EVENT_RETENTION_DAYS = 36500
    _event(dataset.link_a, occurred_at=datetime(2026, 3, 2, 6, 0, tzinfo=UTC))  # Mon 09:00 local
    _event(
        dataset.link_a,
        occurred_at=datetime(2026, 3, 2, 6, 0, tzinfo=UTC),
        is_bot=True,
        user_agent=BOT_UA,
    )

    excluding_bots = queries.hour_weekday_matrix(
        dataset.workspace_a, dataset.link_a, MATRIX_START, MATRIX_END
    )
    including_bots = queries.hour_weekday_matrix(
        dataset.workspace_a, dataset.link_a, MATRIX_START, MATRIX_END, include_bots=True
    )

    assert excluding_bots[0][9] == 1
    assert including_bots[0][9] == 2


@pytest.mark.django_db
def test_hour_weekday_matrix_applies_the_same_retention_floor_as_recent_clicks(link, settings):
    settings.CLICK_EVENT_RETENTION_DAYS = 90
    now = timezone.now()
    old = now - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS + 1)
    recent = now - timedelta(hours=1)
    _event(link, occurred_at=old)
    _event(link, occurred_at=recent)
    today = timezone.localdate()

    matrix = queries.hour_weekday_matrix(link.workspace, link, today - timedelta(days=200), today)

    assert sum(sum(row) for row in matrix) == 1


# --- export_rows ------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_rows_header_then_one_zero_filled_row_per_day(dataset):
    rows = list(queries.export_rows(dataset.workspace_a, dataset.link_a, START, END))
    assert rows[0] == ["date", "clicks", "unique_clicks", "bot_clicks"]
    assert len(rows) == 4
    assert rows[1] == [START.isoformat(), 14, 10, 3]
    assert rows[2] == [(START + timedelta(days=1)).isoformat(), 0, 0, 0]
    assert rows[3] == [END.isoformat(), 7, 7, 0]


@pytest.mark.django_db
def test_export_rows_ignores_other_links_and_workspaces(dataset):
    rows = list(queries.export_rows(dataset.workspace_a, dataset.link_a2, START, END))
    assert rows[1] == [START.isoformat(), 6, 5, 1]
