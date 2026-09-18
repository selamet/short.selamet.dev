"""Optional GeoLite2 lookups.

Self-hosters who do not want a MaxMind account simply leave GEOIP_PATH empty: every
lookup returns blanks and nothing else in the product changes.
"""

import logging

from django.conf import settings
from geoip2.database import Reader

logger = logging.getLogger(__name__)

_BLANK = {"country": "", "city": ""}

# Sentinel distinct from None: None means "already tried to open the database and
# failed", which must not trigger a second attempt on every following click.
_NOT_LOADED = object()
_reader = _NOT_LOADED


def configured():
    return bool(settings.GEOIP_PATH)


def _get_reader():
    """Opens the GeoLite2 database once per process and reuses it: Reader memory-maps
    the file, so re-opening it on every click would pay that cost for no benefit, and
    would eventually exhaust file descriptors under load.
    """
    global _reader
    if _reader is _NOT_LOADED:
        try:
            _reader = Reader(settings.GEOIP_PATH)
        except Exception:
            logger.exception("failed to open the GeoLite2 database at %s", settings.GEOIP_PATH)
            _reader = None
    return _reader


def lookup(ip):
    """Resolve one address to its country code and city name, or blanks on any
    failure: GEOIP_PATH left empty, a database that failed to open, an address the
    database has no entry for, or anything else the underlying library raises. This
    never raises, so a caller never needs its own try/except around it.
    """
    if not configured():
        return dict(_BLANK)
    reader = _get_reader()
    if reader is None:
        return dict(_BLANK)
    try:
        response = reader.city(ip)
    except Exception:
        logger.warning("geoip lookup failed for an address", exc_info=True)
        return dict(_BLANK)
    return {
        "country": response.country.iso_code or "",
        "city": response.city.name or "",
    }
