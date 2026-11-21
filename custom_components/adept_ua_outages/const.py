"""Shared integration settings."""

from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "adept_ua_outages"
CONF_REGION = "region"
CONF_OPERATOR = "operator"
CONF_QUEUE = "queue"
CONF_GRID_SENSOR = "grid_sensor"
CONF_INVERT_GRID = "invert_grid"
EVENT_SCHEDULE_CHANGED = f"{DOMAIN}_schedule_changed"
PANEL_PATH = "ukrainian-outage-schedules"
CARD_URL = f"/{DOMAIN}/schedule-card.js"

KYIV = ZoneInfo("Europe/Kyiv")
UPDATE_INTERVAL = timedelta(minutes=10)
