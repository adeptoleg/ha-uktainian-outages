"""Home Assistant integration for Zakarpattia hourly outage schedules."""

import logging
from datetime import datetime
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CARD_URL,
    CONF_OPERATOR,
    CONF_QUEUE,
    DOMAIN,
    EVENT_SCHEDULE_CHANGED,
    KYIV,
    PANEL_PATH,
    UPDATE_INTERVAL,
)
from .feeds import ScheduleFeeds, source_tls_context
from .schedule import ONE_DAY, PublishedSchedules
from .ua_outages import OPERATORS

OPERATORS_BY_ID = {operator.id: operator for operator in OPERATORS}

_LOGGER = logging.getLogger(__name__)
_PLATFORMS = (Platform.CALENDAR, Platform.SENSOR, Platform.BINARY_SENSOR)


class ScheduleCoordinator(DataUpdateCoordinator[PublishedSchedules]):
    """Fetch the regional schedule and announce revisions to the selected queue."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.queue: str = entry.data[CONF_QUEUE]
        self.operator = OPERATORS_BY_ID[entry.data[CONF_OPERATOR]]
        self.feeds = hass.data[DOMAIN]["feeds"]

    async def _async_update_data(self) -> PublishedSchedules:
        data = await self.feeds.fetch(self.operator)
        if self.data is not None:
            today = datetime.now(KYIV).date()
            changed = []
            for day in (today, today + ONE_DAY):
                before = self.data.days.get(day)
                after = data.days.get(day)
                before_state = before.state(self.queue) if before else (None, None)
                after_state = after.state(self.queue) if after else (None, None)
                if before_state != after_state:
                    changed.append(day.isoformat())
            if changed:
                self.hass.bus.async_fire(
                    EVENT_SCHEDULE_CHANGED,
                    {
                        "region": self.operator.region,
                        "operator": self.operator.id,
                        "queue": self.queue,
                        "dates": changed,
                    },
                )
        return data


type ScheduleEntry = ConfigEntry[ScheduleCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Make the dashboard card available to Home Assistant."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL, str(Path(__file__).with_name("schedule-card.js")), False
            )
        ]
    )
    frontend.add_extra_js_url(hass, CARD_URL)
    tls = await hass.async_add_executor_job(source_tls_context)
    hass.data[DOMAIN] = {
        "entries": set(),
        "feeds": ScheduleFeeds(async_get_clientsession(hass), tls),
    }
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ScheduleEntry) -> bool:
    """Set up the selected subqueue and optional grid measurement."""
    coordinator = ScheduleCoordinator(hass, entry)
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    active_entries = hass.data[DOMAIN]["entries"]
    if not active_entries:
        await async_register_panel(
            hass,
            frontend_url_path=PANEL_PATH,
            webcomponent_name="adept-ua-outages-panel",
            sidebar_title="Графіки світла України",
            sidebar_icon="mdi:transmission-tower",
            module_url=CARD_URL,
            trust_external=True,
        )
    active_entries.add(entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ScheduleEntry) -> bool:
    """Unload the integration's entities."""
    if not await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
        return False
    active_entries = hass.data[DOMAIN]["entries"]
    active_entries.discard(entry.entry_id)
    if not active_entries:
        frontend.async_remove_panel(hass, PANEL_PATH)
    return True
