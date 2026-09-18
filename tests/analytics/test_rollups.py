"""Tests for apps.analytics.rollups: the incremental upsert into DailyLinkStat and
DailyLinkBreakdown, and the from-scratch rebuild of both from raw ClickEvent rows."""

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.analytics import attribution, rollups
from apps.analytics.models import ClickEvent, DailyClickIdentity, DailyLinkBreakdown, DailyLinkStat
from apps.analytics.tasks import record_click
from apps.core.privacy import hash_ip
from apps.links import services as link_services
from apps.workspaces import services as workspace_services
from apps.workspaces.models import Membership, Role
from tests.redirects.conftest import DESKTOP_UA

IP_A = hash_ip("203.0.113.9")
IP_B = hash_ip("203.0.113.10")
BOT_UA = "Googlebot/2.1 (+http://www.google.com/bot.html)"


def _click(link, **overrides):
    """Records one click the way the redirect view does, through record_click, so
    these tests exercise the same wiring production uses: record_click calls
    rollups.apply_event once the ClickEvent and the click counter are saved (see
    apps.analytics.tasks)."""
    payload = {
        "occurred_at": timezone.now().isoformat(),
        "ip_hash": IP_A,
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


def _event(link, **overrides):
    """Builds a raw ClickEvent directly, for tests that exercise rollups.apply_event
    on fields (country, city) that record_click does not populate until the
    geo-resolution issue lands (see apps.analytics.geo), and for tests that need
    precise control over occurred_at."""
    defaults = {
        "link": link,
        "workspace": link.workspace,
        "occurred_at": timezone.now(),
        "ip_hash": IP_A,
        "user_agent": DESKTOP_UA,
        "is_bot": False,
    }
    defaults.update(overrides)
    return ClickEvent.objects.create(**defaults)


def _membership(owner, slug):
    workspace = workspace_services.create_workspace(owner, name=slug, slug=slug)
    return Membership.objects.get(workspace=workspace, user=owner, role=Role.OWNER)


@pytest.mark.django_db
def test_one_click_produces_a_daily_stat_row(link):
    _click(link)
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.workspace_id == link.workspace_id
    assert stat.date == timezone.localdate()
    assert (stat.clicks, stat.unique_clicks, stat.bot_clicks) == (1, 1, 0)


@pytest.mark.django_db
def test_a_second_click_from_the_same_visitor_raises_clicks_not_unique_clicks(link):
    _click(link)
    _click(link)
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.clicks == 2
    assert stat.unique_clicks == 1


@pytest.mark.django_db
def test_a_different_visitor_raises_both_counts(link):
    _click(link, ip_hash=IP_A)
    _click(link, ip_hash=IP_B)
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.clicks == 2
    assert stat.unique_clicks == 2


@pytest.mark.django_db
def test_a_bot_click_counts_but_never_as_unique(link):
    _click(link, user_agent=BOT_UA)
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.clicks == 1
    assert stat.bot_clicks == 1
    assert stat.unique_clicks == 0


@pytest.mark.django_db
def test_two_clicks_sharing_an_identity_produce_one_unique_regardless_of_order(link):
    rollups.apply_event(_event(link, ip_hash=IP_A, user_agent=DESKTOP_UA))
    rollups.apply_event(_event(link, ip_hash=IP_A, user_agent=DESKTOP_UA))
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.clicks == 2
    assert stat.unique_clicks == 1
    assert DailyClickIdentity.objects.filter(link=link).count() == 1


@pytest.mark.django_db
def test_a_bot_click_never_blocks_a_later_genuine_click_with_the_same_identity(link):
    # Same ip_hash and user_agent for both: only is_bot differs, which _click() (via
    # useragent.is_bot()) cannot vary independently of the user agent string, so this
    # goes through apply_event() directly.
    rollups.apply_event(_event(link, ip_hash=IP_A, user_agent=DESKTOP_UA, is_bot=True))
    rollups.apply_event(_event(link, ip_hash=IP_A, user_agent=DESKTOP_UA, is_bot=False))
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.clicks == 2
    assert stat.bot_clicks == 1
    assert stat.unique_clicks == 1


@pytest.mark.django_db
def test_a_racing_identity_insert_is_counted_as_non_unique_not_an_error(link, monkeypatch):
    def boom(**kwargs):
        raise IntegrityError("duplicate key value violates unique constraint")

    monkeypatch.setattr(DailyClickIdentity.objects, "create", boom)
    rollups.apply_event(_event(link))
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.clicks == 1
    assert stat.unique_clicks == 0


@pytest.mark.django_db
def test_breakdown_rows_skip_empty_dimensions(link):
    event = _event(link, country="", city="", referrer_host="", utm_source="instagram")
    rollups.apply_event(event)
    rows = set(DailyLinkBreakdown.objects.filter(link=link).values_list("dimension", "value"))
    assert rows == {("utm_source", "instagram")}
    assert not DailyLinkBreakdown.objects.filter(dimension="country").exists()


@pytest.mark.django_db
def test_two_clicks_from_the_same_country_accumulate_one_row(link):
    rollups.apply_event(_event(link, country="US"))
    rollups.apply_event(_event(link, country="US", ip_hash=IP_B))
    row = DailyLinkBreakdown.objects.get(link=link, dimension="country", value="US")
    assert row.clicks == 2
    assert row.workspace_id == link.workspace_id


@pytest.mark.django_db
def test_rebuild_reproduces_exactly_the_same_rows(link):
    rollups.apply_event(_event(link, country="US"))
    rollups.apply_event(_event(link, country="US", ip_hash=IP_B))
    rollups.apply_event(_event(link, user_agent=BOT_UA, is_bot=True))
    today = timezone.localdate()

    before_stat = DailyLinkStat.objects.get(link=link, date=today)
    before = (before_stat.clicks, before_stat.unique_clicks, before_stat.bot_clicks)
    before_breakdown = list(
        DailyLinkBreakdown.objects.filter(link=link, date=today)
        .order_by("dimension", "value")
        .values("dimension", "value", "clicks")
    )
    before_identities = set(
        DailyClickIdentity.objects.filter(link=link, date=today).values_list("identity", flat=True)
    )

    DailyLinkStat.objects.filter(link=link).delete()
    DailyLinkBreakdown.objects.filter(link=link).delete()
    DailyClickIdentity.objects.filter(link=link).delete()
    rollups.rebuild(link, today)

    after_stat = DailyLinkStat.objects.get(link=link, date=today)
    after_breakdown = list(
        DailyLinkBreakdown.objects.filter(link=link, date=today)
        .order_by("dimension", "value")
        .values("dimension", "value", "clicks")
    )
    after_identities = set(
        DailyClickIdentity.objects.filter(link=link, date=today).values_list("identity", flat=True)
    )
    assert (after_stat.clicks, after_stat.unique_clicks, after_stat.bot_clicks) == before
    assert after_breakdown == before_breakdown
    assert after_identities == before_identities


@pytest.mark.django_db
def test_rebuild_corrects_tampered_numbers_and_identities(link):
    rollups.apply_event(_event(link, country="US"))
    today = timezone.localdate()
    DailyLinkStat.objects.filter(link=link, date=today).update(clicks=999, unique_clicks=999)
    DailyLinkBreakdown.objects.filter(link=link, date=today).update(clicks=999)
    # Tamper with the identity table too: add a bogus extra row and drop the real one,
    # so a rebuild that merely trusted what was there instead of recomputing it would
    # keep miscounting.
    DailyClickIdentity.objects.filter(link=link, date=today).delete()
    DailyClickIdentity.objects.create(
        link=link, workspace=link.workspace, date=today, identity="bogus"
    )

    rollups.rebuild(link, today)

    stat = DailyLinkStat.objects.get(link=link, date=today)
    assert (stat.clicks, stat.unique_clicks) == (1, 1)
    breakdown = DailyLinkBreakdown.objects.get(
        link=link, date=today, dimension="country", value="US"
    )
    assert breakdown.clicks == 1
    identities = list(DailyClickIdentity.objects.filter(link=link, date=today))
    assert len(identities) == 1
    assert identities[0].identity != "bogus"


@pytest.mark.django_db
def test_rollups_never_cross_workspaces(owner):
    membership_a = _membership(owner, "workspace-a")
    membership_b = _membership(owner, "workspace-b")
    link_a = link_services.create_link(
        membership_a, destination_url="https://example.com/a", code="link-a"
    )
    link_b = link_services.create_link(
        membership_b, destination_url="https://example.com/b", code="link-b"
    )

    rollups.apply_event(_event(link_a, country="US"))
    rollups.apply_event(_event(link_b, country="US"))

    stat_a = DailyLinkStat.objects.get(link=link_a)
    stat_b = DailyLinkStat.objects.get(link=link_b)
    assert stat_a.workspace_id == link_a.workspace_id
    assert stat_b.workspace_id == link_b.workspace_id
    assert stat_a.pk != stat_b.pk

    breakdown_a = DailyLinkBreakdown.objects.get(link=link_a, dimension="country", value="US")
    breakdown_b = DailyLinkBreakdown.objects.get(link=link_b, dimension="country", value="US")
    assert breakdown_a.clicks == 1
    assert breakdown_b.clicks == 1
    assert breakdown_a.workspace_id != breakdown_b.workspace_id


@pytest.mark.django_db
def test_day_boundary_uses_the_workspace_timezone(owner):
    membership = _membership(owner, "istanbul-shop")
    membership.workspace.timezone = "Europe/Istanbul"
    membership.workspace.save(update_fields=["timezone"])
    link = link_services.create_link(
        membership, destination_url="https://example.com/x", code="istanbul-link"
    )
    occurred_at = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    event = _event(link, occurred_at=occurred_at)

    day = rollups.local_date(event)

    assert day == datetime(2026, 1, 2, tzinfo=UTC).date()
    rollups.apply_event(event)
    stat = DailyLinkStat.objects.get(link=link)
    assert stat.date == day


@pytest.mark.django_db
def test_local_date_falls_back_to_utc_for_an_unusable_workspace_timezone(link):
    # Bypasses validate_timezone (which the model normally enforces) to simulate data
    # that somehow ended up with a timezone zoneinfo cannot load.
    link.workspace.timezone = "Not/AZone"
    link.workspace.save(update_fields=["timezone"])
    occurred_at = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    event = _event(link, occurred_at=occurred_at)

    assert rollups.local_date(event) == occurred_at.date()
