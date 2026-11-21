"""Load community and operator schedules with one shared request per operator."""

import logging
from asyncio import Lock, timeout
from collections import defaultdict
from datetime import datetime
from time import monotonic

from aiohttp import ClientError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import KYIV
from .schedule import ONE_DAY, PublishedSchedules, parse_community_schedule
from .ua_outages import Fetcher, FetchError, Operator
from .ua_outages.http import ssl_context
from .ua_outages.providers.base import AddressSource

_LOGGER = logging.getLogger(__name__)
RAW_HOST = "raw.githubusercontent.com"
OE_BASE = f"https://{RAW_HOST}/yaroslav2901/OE_OUTAGE_DATA/main/data/"
OE_FILES = {
    "cherkasy-oe": "Cherkasyoblenergo",
    "chernihiv-oe": "Chernihivoblenergo",
    "kharkiv-oe": "Kharkivoblenerho",
    "khmelnytskyi-oe": "Khmelnytskoblenerho",
    "lviv-oe": "Lvivoblenerho",
    "poltava-oe": "Poltavaoblenergo",
    "prykarpattia-oe": "Prykarpattiaoblenerho",
    "rivne-oe": "Rivneoblenergo",
    "ternopil-oe": "Ternopiloblenerho",
    "zakarpattia-oe": "Zakarpattiaoblenerho",
    "zaporizhzhia-oe": "Zaporizhzhiaoblenergo",
    "zhytomyr-oe": "Zhytomyroblenergo",
}
MIRRORS = {key: f"{OE_BASE}{name}.json" for key, name in OE_FILES.items()}
MIRRORS["vinnytsia-oe"] = (
    f"https://{RAW_HOST}/vn-progr/gpv-voe-vinnytsia/main/data/Vinnytsiaoblenerho.json"
)


def source_tls_context():
    """Trust the host's CA store and the SDK's bundled certificate chain."""
    context = ssl_context()
    context.load_default_certs()
    return context


def supports_schedules(operator: Operator) -> bool:
    return operator.id in MIRRORS or any(
        not isinstance(source, AddressSource) for source in operator.sources
    )


class ScheduleFeeds:
    def __init__(self, session, tls) -> None:
        self.session = session
        self.tls = tls
        self._locks = defaultdict(Lock)
        self._cache: dict[str, tuple[float, PublishedSchedules]] = {}

    async def fetch(self, operator: Operator) -> PublishedSchedules:
        if not supports_schedules(operator):
            return PublishedSchedules({})
        async with self._locks[operator.id]:
            cached = self._cache.get(operator.id)
            if cached is not None and monotonic() - cached[0] < 120:
                return cached[1]
            result = await self._fetch(operator)
            self._cache[operator.id] = (monotonic(), result)
            return result

    async def _fetch(self, operator: Operator) -> PublishedSchedules:
        now = datetime.now(KYIV)
        answered = False
        if url := MIRRORS.get(operator.id):
            try:
                http = Fetcher(self.session, frozenset({RAW_HOST}), tls=self.tls)
                days = parse_community_schedule(
                    (await http.get(url)).json(), now.date()
                )
                if days:
                    return PublishedSchedules(days, url)
                answered = True
            except (
                FetchError,
                ClientError,
                TimeoutError,
                ValueError,
                TypeError,
                OSError,
            ):
                _LOGGER.debug(
                    "Community schedule unavailable for %s", operator.id, exc_info=True
                )

        partial = None
        for source in operator.sources:
            if isinstance(source, AddressSource):
                continue
            try:
                async with timeout(30):
                    fetcher = Fetcher(self.session, source.hosts, tls=self.tls)
                    found = await source.fetch(fetcher, now)
            except Exception:
                _LOGGER.debug("Schedule source %s failed", source.name, exc_info=True)
                continue
            answered = True
            days = {
                day: schedule
                for day, schedule in found.items()
                if day in (now.date(), now.date() + ONE_DAY)
            }
            result = PublishedSchedules(days, source.link or operator.site)
            if any(day.groups for day in days.values()):
                return result
            if days and partial is None:
                partial = result
        if answered:
            return partial or PublishedSchedules({})
        raise UpdateFailed(f"Schedule sources unavailable for {operator.id}")
