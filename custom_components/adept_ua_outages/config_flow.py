"""Select a territory, operator and outage group."""

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from . import OPERATORS_BY_ID
from .const import (
    CONF_GRID_SENSOR,
    CONF_INVERT_GRID,
    CONF_OPERATOR,
    CONF_QUEUE,
    CONF_REGION,
    DOMAIN,
)
from .feeds import supports_schedules
from .schedule import GROUP_PATTERN
from .ua_outages import REGIONS

_GRID_FIELDS = {
    vol.Optional(CONF_GRID_SENSOR): EntitySelector(
        EntitySelectorConfig(filter={"domain": "binary_sensor"})
    ),
    vol.Optional(CONF_INVERT_GRID, default=False): BooleanSelector(),
}
_REGIONS = {region.id: region for region in REGIONS}


class OutageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one config entry for a group of a specific operator."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._region = _REGIONS[user_input[CONF_REGION]]
            if len(self._region.operators) > 1:
                return await self.async_step_operator()
            return await self.async_step_operator(
                {CONF_OPERATOR: self._region.operators[0]}
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGION): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=region.id, label=region.name)
                                for region in sorted(
                                    REGIONS, key=lambda region: region.name
                                )
                            ]
                        )
                    ),
                }
            ),
        )

    async def async_step_operator(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._operator = OPERATORS_BY_ID[user_input[CONF_OPERATOR]]
            return await self.async_step_queue()
        return self.async_show_form(
            step_id="operator",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OPERATOR): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=key, label=OPERATORS_BY_ID[key].name
                                )
                                for key in self._region.operators
                            ]
                        )
                    ),
                }
            ),
        )

    async def async_step_queue(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            queue = user_input[CONF_QUEUE].strip().replace("-", ".").replace(",", ".")
            if GROUP_PATTERN.fullmatch(queue):
                await self.async_set_unique_id(f"{self._operator.id}:{queue}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{self._operator.name} · {queue}",
                    data={
                        **user_input,
                        CONF_QUEUE: queue,
                        CONF_REGION: self._region.id,
                        CONF_OPERATOR: self._operator.id,
                    },
                )
            errors[CONF_QUEUE] = "invalid_queue"
        return self.async_show_form(
            step_id="queue",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_QUEUE): SelectSelector(
                        SelectSelectorConfig(
                            options=list(self._operator.groups),
                            custom_value=True,
                        )
                    ),
                    **_GRID_FIELDS,
                }
            ),
            description_placeholders={
                "operator": self._operator.name,
                "note": ""
                if supports_schedules(self._operator)
                else self._operator.note or "",
            },
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data={
                    **{
                        key: entry.data[key]
                        for key in (CONF_REGION, CONF_OPERATOR, CONF_QUEUE)
                    },
                    **user_input,
                },
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_GRID_FIELDS), entry.data
            ),
        )
