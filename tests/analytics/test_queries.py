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

from apps.analytics import queries
from apps.analytics.models import ClickEvent, DailyLinkBreakdown, DailyLinkStat, Dimension
from apps.links import services as link_services
from apps.links.models import Link
from apps.workspaces import services as workspace_services
from apps.workspaces.models import Membership, Role
from tests.redirects.conftest import DESKTOP_UA

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


def _breakdown(link, day, value, clicks, dimension=Dimension.COUNTRY):
    DailyLinkBreakdown.objects.create(
        link=link,
        workspace=link.workspace,
        date=day,
        dimension=dimension,
        value=value,
        clicks=clicks,
    )


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
        "unique_clicks": 24,  # 17 + (5 + 2)
        "bot_clicks": 4,  # 3 + 1
        "previous_clicks": 12,  # link_a2 has no rows in the previous period
        "delta_pct": 116.7,
    }


@pytest.mark.django_db
def test_summary_with_no_previous_clicks_reports_a_flat_100_or_0_percent_delta(dataset):
    no_previous = queries.summary(
        dataset.workspace_a, dataset.link_a, start=END, end=END
    )  # a range with clicks but nothing before PREVIOUS_START in this dataset either
    assert no_previous["previous_clicks"] == 0
    assert no_previous["delta_pct"] == 100.0

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
        {"code": "link-a", "title": "Alpha", "clicks": 21},
        {"code": "link-a2", "title": "Alpha Two", "clicks": 9},
    ]


@pytest.mark.django_db
def test_leaderboard_limit(dataset):
    rows = queries.leaderboard(dataset.workspace_a, START, END, limit=1)
    assert rows == [{"code": "link-a", "title": "Alpha", "clicks": 21}]


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
def test_hour_weekday_matrix_shape_and_a_known_peak(dataset):
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

    matrix = queries.hour_weekday_matrix(
        dataset.workspace_a, dataset.link_a, MATRIX_START, MATRIX_END
    )

    assert len(matrix) == 7
    assert all(len(row) == 24 for row in matrix)
    assert matrix[0][9] == 4  # the known peak: Monday, 09:00 local
    assert matrix[0][1] == 1
    assert matrix[2][14] == 1
    assert sum(sum(row) for row in matrix) == 6


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
