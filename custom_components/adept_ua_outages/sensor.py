"""Published schedule status and next known outage."""

from datetime import UTC, datetime
from typing import ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScheduleEntry
from .const import KYIV
from .entity import ScheduleEntity
from .feeds import supports_schedules
from .schedule import GROUP_PATTERN, ONE_DAY, render_slots
from .solar import daylight
from .ua_outages import EMERGENCY


async def async_setup_entry(
    hass: HomeAssistant, entry: ScheduleEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ScheduleStatus(coordinator, "status"),
            NextOutage(coordinator, "next_outage"),
            NextRestoration(coordinator, "next_restoration"),
        ]
    )


class ScheduleStatus(ScheduleEntity, SensorEntity):
    """Show what the published hourly schedule says about the current time."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        "unpublished",
        "unsupported",
        "emergency",
        "possible_outage",
        "outage_scheduled",
        "no_outage_scheduled",
    ]

    @property
    def native_value(self) -> str:
        now = datetime.now(UTC)
        if not supports_schedules(self.coordinator.operator):
            return "unsupported"
        day, intervals = next(self.published_days(now))
        data = self.coordinator.data
        schedule = data.days.get(day) if data else None
        if schedule and schedule.unknown.get(self.coordinator.queue) == EMERGENCY:
            return "emergency"
        if intervals is None:
            return "unpublished"
        for interval in intervals:
            if interval.start <= now < interval.end:
                return "possible_outage" if interval.possible else "outage_scheduled"
        return "no_outage_scheduled"

    @property
    def extra_state_attributes(self) -> dict:
        now = datetime.now(UTC)
        today = now.astimezone(KYIV).date()
        data = self.coordinator.data if self.available else None
        operator = self.coordinator.operator
        published = data.days if data else {}
        days = (today, today + ONE_DAY)
        return {
            "all_queues": {
                day.isoformat(): {
                    queue: render_slots(day, intervals)
                    for queue, intervals in published[day].groups.items()
                    if GROUP_PATTERN.fullmatch(queue)
                }
                if day in published
                else {}
                for day in days
            },
            "queue": self.coordinator.queue,
            "operator": operator.id,
            "adept_ua_outages": True,
            "operator_name": operator.name,
            "region": operator.region,
            "groups": sorted(
                {self.coordinator.queue}
                | {
                    queue
                    for day in published.values()
                    for queue in day.mentioned_groups()
                }
            )
            if published
            else list(operator.groups),
            "daylight": {
                day.isoformat(): daylight(
                    day, self.hass.config.latitude, self.hass.config.longitude
                )
                for day in days
            },
            "next_outage": (
                outage.isoformat() if (outage := self.scheduled_outage(now)) else None
            ),
            "next_restoration": (
                restoration.isoformat()
                if (restoration := self.scheduled_restoration(now))
                else None
            ),
            "source": (data.source if data else None) or operator.site,
            "schedule_images": {
                day.isoformat(): published[day].image_url
                for day in days
                if day in published and published[day].image_url
            },
            "schedule": {
                day.isoformat(): (
                    None
                    if intervals is None or not self.available
                    else [
                        {
                            "start": interval.start.astimezone(KYIV).isoformat(),
                            "end": interval.end.astimezone(KYIV).isoformat(),
                            "possible": interval.possible,
                        }
                        for interval in intervals
                    ]
                )
                for day, intervals in self.published_days(now)
            },
        }


class NextOutage(ScheduleEntity, SensorEntity):
    """Expose the next published start time for dashboard and automations."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return self.scheduled_outage(datetime.now(UTC))


class NextRestoration(ScheduleEntity, SensorEntity):
    """Expose the first known end of a current or future outage."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return self.scheduled_restoration(datetime.now(UTC))
