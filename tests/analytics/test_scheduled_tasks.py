"""Tests for the four scheduled jobs in apps.analytics.tasks (rebuild_daily_stats,
purge_click_events, rotate_ip_salt, expire_links) and the enqueue_scheduled
management command that puts one of them on the worker's queue."""

import logging
from datetime import UTC, datetime, time, timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import QuerySet
from django.utils import timezone

from apps.analytics import rollups
from apps.analytics.management.commands import enqueue_scheduled
from apps.analytics.models import ClickEvent, DailyClickIdentity, DailyLinkStat
from apps.analytics.tasks import (
    expire_links,
    purge_click_events,
    rebuild_daily_stats,
    rotate_ip_salt,
)
from apps.core.privacy import daily_salt
from apps.links import services as link_services
from apps.links.models import Link
from apps.redirects import cache as redirect_cache
from tests.redirects.conftest import DESKTOP_UA


def _event(link, **overrides):
    defaults = {
        "link": link,
        "workspace": link.workspace,
        "occurred_at": datetime.now(tz=UTC),
        "ip_hash": "hash-a",
        "user_agent": DESKTOP_UA,
        "is_bot": False,
    }
    defaults.update(overrides)
    return ClickEvent.objects.create(**defaults)


def _at_noon(day):
    return datetime.combine(day, time(12, 0), tzinfo=UTC)


# --- rebuild_daily_stats -------------------------------------------------------------


@pytest.mark.django_db
def test_rebuild_daily_stats_default_rebuilds_yesterday_for_every_link_with_events(membership):
    yesterday = datetime.now(tz=UTC).date() - timedelta(days=1)
    active_link = link_services.create_link(
        membership, destination_url="https://example.com/a", code="active-link"
    )
    idle_link = link_services.create_link(
        membership, destination_url="https://example.com/b", code="idle-link"
    )
    rollups.apply_event(_event(active_link, occurred_at=_at_noon(yesterday)))
    DailyLinkStat.objects.filter(link=active_link, date=yesterday).update(
        clicks=999, unique_clicks=999
    )

    rebuild_daily_stats.enqueue()

    stat = DailyLinkStat.objects.get(link=active_link, date=yesterday)
    assert (stat.clicks, stat.unique_clicks) == (1, 1)
    assert not DailyLinkStat.objects.filter(link=idle_link).exists()


@pytest.mark.django_db
def test_rebuild_daily_stats_with_an_explicit_date_rebuilds_that_day(link):
    # A task backend that persists its arguments (django_tasks_db in production, and
    # even the in-process ImmediateBackend used in tests -- see
    # django.tasks.base.TaskResult.__post_init__) requires them to be JSON-safe, so a
    # caller passes the day as an ISO string, never a raw date; rebuild_daily_stats
    # accepts exactly that (see _coerce_day).
    day = datetime.now(tz=UTC).date() - timedelta(days=10)
    rollups.apply_event(_event(link, occurred_at=_at_noon(day)))
    DailyLinkStat.objects.filter(link=link, date=day).update(clicks=42)

    rebuild_daily_stats.enqueue(day.isoformat())

    assert DailyLinkStat.objects.get(link=link, date=day).clicks == 1


@pytest.mark.django_db
def test_rebuild_daily_stats_also_corrects_the_previous_local_day_for_a_western_workspace(
    membership,
):
    # I4: Honolulu is UTC-10, no DST, so an event just after UTC midnight on
    # `yesterday` still falls on the day before that in Honolulu's own calendar --
    # its rollup belongs to `yesterday - 1`, a day the old single-day rebuild (only
    # ever `yesterday`) would never revisit for a workspace this far west of UTC.
    membership.workspace.timezone = "Pacific/Honolulu"
    membership.workspace.save(update_fields=["timezone"])
    link = link_services.create_link(
        membership, destination_url="https://example.com/hi", code="honolulu-link"
    )
    yesterday = datetime.now(tz=UTC).date() - timedelta(days=1)
    day_before = yesterday - timedelta(days=1)
    event = _event(link, occurred_at=datetime.combine(yesterday, time(0, 30), tzinfo=UTC))
    assert rollups.local_date(event) == day_before
    rollups.apply_event(event)
    DailyLinkStat.objects.filter(link=link, date=day_before).update(clicks=999, unique_clicks=999)

    rebuild_daily_stats.enqueue()

    stat = DailyLinkStat.objects.get(link=link, date=day_before)
    assert (stat.clicks, stat.unique_clicks) == (1, 1)


@pytest.mark.django_db
def test_rebuild_daily_stats_refuses_a_day_past_retention_and_leaves_it_alone(
    settings, link, caplog
):
    settings.CLICK_EVENT_RETENTION_DAYS = 90
    stale_day = timezone.now().date() - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS + 1)
    DailyLinkStat.objects.create(
        link=link, workspace=link.workspace, date=stale_day, clicks=5, unique_clicks=5
    )

    with caplog.at_level(logging.WARNING, logger="apps.analytics.tasks"):
        rebuild_daily_stats.enqueue(stale_day.isoformat())

    stat = DailyLinkStat.objects.get(link=link, date=stale_day)
    assert stat.clicks == 5  # left untouched, not zeroed out
    assert "refused" in caplog.text


@pytest.mark.django_db
def test_rebuild_daily_stats_processes_a_day_exactly_at_the_retention_boundary(settings, link):
    settings.CLICK_EVENT_RETENTION_DAYS = 90
    boundary_day = timezone.now().date() - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS)
    rollups.apply_event(_event(link, occurred_at=_at_noon(boundary_day)))
    DailyLinkStat.objects.filter(link=link, date=boundary_day).update(clicks=999)

    rebuild_daily_stats.enqueue(boundary_day.isoformat())

    assert DailyLinkStat.objects.get(link=link, date=boundary_day).clicks == 1


# --- purge_click_events ---------------------------------------------------------------


@pytest.mark.django_db
def test_purge_click_events_deletes_old_events_and_identities_in_batches(settings, link):
    settings.ANALYTICS_PURGE_BATCH_SIZE = 2
    old = datetime.now(tz=UTC) - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS + 1)
    recent = datetime.now(tz=UTC) - timedelta(days=1)
    for i in range(5):
        _event(link, occurred_at=old, ip_hash=f"old-{i}")
    kept_event = _event(link, occurred_at=recent, ip_hash="keep")
    DailyClickIdentity.objects.create(
        link=link, workspace=link.workspace, date=old.date(), identity="stale"
    )
    DailyClickIdentity.objects.create(
        link=link, workspace=link.workspace, date=recent.date(), identity="fresh"
    )
    DailyLinkStat.objects.create(link=link, workspace=link.workspace, date=old.date(), clicks=5)

    purge_click_events.enqueue()

    assert ClickEvent.objects.filter(pk=kept_event.pk).exists()
    assert ClickEvent.objects.filter(ip_hash__startswith="old-").count() == 0
    assert not DailyClickIdentity.objects.filter(identity="stale").exists()
    assert DailyClickIdentity.objects.filter(identity="fresh").exists()
    # Rollups are never purged, only the raw events and identities behind them.
    assert DailyLinkStat.objects.filter(link=link, date=old.date()).exists()


@pytest.mark.django_db
def test_purge_click_events_logs_how_many_it_removed(caplog, link):
    old = datetime.now(tz=UTC) - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS + 1)
    _event(link, occurred_at=old)
    _event(link, occurred_at=old)

    with caplog.at_level(logging.INFO, logger="apps.analytics.tasks"):
        purge_click_events.enqueue()

    assert "events=2" in caplog.text


# --- rotate_ip_salt ---------------------------------------------------------------------


@pytest.mark.django_db
def test_rotate_ip_salt_leaves_an_already_cached_salt_unchanged():
    # C3 regression test: rotate_ip_salt must never replace a salt already in use --
    # a visitor who clicked before this job ran and hashed against `before_today`
    # must still hash the same way after it runs, or they get counted as two unique
    # visitors instead of one (see apps.core.privacy.ensure_daily_salt).
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    before_today = daily_salt(today)
    before_yesterday = daily_salt(yesterday)

    rotate_ip_salt.enqueue()

    assert daily_salt(today) == before_today
    assert daily_salt(yesterday) == before_yesterday


# --- expire_links -----------------------------------------------------------------------


@pytest.mark.django_db
def test_expire_links_disables_expired_links_and_invalidates_their_cache(
    link, django_capture_on_commit_callbacks
):
    link.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
    link.save(update_fields=["expires_at"])
    redirect_cache.set_payload(link.code, redirect_cache.payload_from_link(link))

    with django_capture_on_commit_callbacks(execute=True):
        expire_links.enqueue()

    link.refresh_from_db()
    assert link.status == Link.Status.DISABLED
    assert redirect_cache.get_payload(link.code) is None


@pytest.mark.django_db
def test_expire_links_disables_links_over_their_max_clicks(link):
    link.max_clicks = 5
    link.click_count = 5
    link.save(update_fields=["max_clicks", "click_count"])

    expire_links.enqueue()

    link.refresh_from_db()
    assert link.status == Link.Status.DISABLED


@pytest.mark.django_db
def test_expire_links_leaves_healthy_links_alone(link):
    link.expires_at = datetime.now(tz=UTC) + timedelta(days=1)
    link.max_clicks = 100
    link.save(update_fields=["expires_at", "max_clicks"])

    expire_links.enqueue()

    link.refresh_from_db()
    assert link.status == Link.Status.ACTIVE


@pytest.mark.django_db
def test_expire_links_never_disables_a_link_without_invalidating_it(
    membership, monkeypatch, django_capture_on_commit_callbacks
):
    """Regression test for a race in the previous implementation: it captured the
    codes to invalidate with one query, then called due.update(...), which
    re-evaluated the same expires_at/max_clicks filter as a second statement. A link
    that only became eligible in the gap between the two (a click landing right as
    this ran, pushing click_count past max_clicks) would then be swept up by that
    second, re-evaluated filter and disabled -- without its code ever having been
    captured, so its cached payload was never invalidated and kept serving stale
    "active" redirects until the cache entry's own TTL expired.

    Simulated by monkeypatching QuerySet.update itself, at the class level, to land
    that click the first time anything calls .update() -- which is exactly the
    disabling update, whichever queryset it ends up being called against -- rather
    than hooking a call shape (e.g. a `pk__in` kwarg) only the fixed implementation
    happens to use. This way the same test fails against the old due.update()
    (which re-evaluates the filter and would disable racing_link too, without ever
    having captured its code) and passes against the fix.
    """
    due_link = link_services.create_link(
        membership, destination_url="https://example.com/due", code="due-link"
    )
    due_link.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
    due_link.save(update_fields=["expires_at"])
    redirect_cache.set_payload(due_link.code, redirect_cache.payload_from_link(due_link))

    racing_link = link_services.create_link(
        membership, destination_url="https://example.com/racing", code="racing-link"
    )
    racing_link.max_clicks = 5
    racing_link.click_count = 4
    racing_link.save(update_fields=["max_clicks", "click_count"])
    redirect_cache.set_payload(racing_link.code, redirect_cache.payload_from_link(racing_link))

    original_update = QuerySet.update
    triggered = False

    def racing_update(self, **kwargs):
        nonlocal triggered
        if not triggered:
            triggered = True
            # The click that crosses max_clicks, landing after `due` was already
            # read but before the disabling update runs.
            Link.objects.filter(pk=racing_link.pk).update(click_count=5)
        return original_update(self, **kwargs)

    monkeypatch.setattr(QuerySet, "update", racing_update)

    with django_capture_on_commit_callbacks(execute=True):
        expire_links.enqueue()

    due_link.refresh_from_db()
    racing_link.refresh_from_db()
    assert due_link.status == Link.Status.DISABLED
    assert redirect_cache.get_payload(due_link.code) is None
    # racing_link crossed max_clicks only after expire_links had already decided
    # what to disable this run: it must be left alone entirely -- both status and
    # cache -- rather than disabled without its cache invalidated. It is caught on
    # the next run instead (every 10 minutes -- see docker/crontab).
    assert racing_link.status == Link.Status.ACTIVE
    assert redirect_cache.get_payload(racing_link.code) is not None


# --- enqueue_scheduled --------------------------------------------------------------------


def test_enqueue_scheduled_enqueues_exactly_the_named_task(monkeypatch):
    calls = []

    class _FakeTask:
        def __init__(self, name):
            self.name = name
            self.id = f"fake-{name}"

        def enqueue(self):
            calls.append(self.name)
            return self

    fake_tasks = {name: _FakeTask(name) for name in enqueue_scheduled.TASKS}
    monkeypatch.setattr(enqueue_scheduled, "TASKS", fake_tasks)

    call_command("enqueue_scheduled", "rotate_ip_salt")

    assert calls == ["rotate_ip_salt"]


def test_enqueue_scheduled_exits_non_zero_for_an_unknown_name():
    with pytest.raises(CommandError):
        call_command("enqueue_scheduled", "not-a-real-task")
