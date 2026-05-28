"""Config flow for OwnerRez Lock Manager.

Step 1 (user):  API credentials + property ID  →  validated against live API
Step 2 (locks): Lock entities, code slots, primary lock, notify service,
                advanced timing options
Options flow:   Re-configure any step-2 field without re-entering credentials
"""
from __future__ import annotations

import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE,
    CONF_CHECKIN_BUFFER_MINUTES,
    CONF_CODE_SLOTS,
    CONF_LOCK_ENTITIES,
    CONF_LOCK_SERVICE_TYPE,
    CONF_LOOKBACK_DAYS,
    CONF_LOOKAHEAD_DAYS,
    CONF_NOTIFY_SERVICE,
    CONF_PRIMARY_LOCK,
    CONF_PROPERTY_ID,
    CONF_TOKEN,
    CONF_USERNAME,
    DEFAULT_CHECKIN_BUFFER_MINUTES,
    DEFAULT_LOOKBACK,
    DEFAULT_LOOKAHEAD,
    DOMAIN,
    LOCK_SERVICE_OPTIONS,
    LOCK_SERVICE_ZWAVE,
)

_LOGGER = logging.getLogger(__name__)

# Voluptuous schema for lock / advanced settings (reused in both flows)
def _locks_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LOCK_ENTITIES,
                default=defaults.get(CONF_LOCK_ENTITIES, ""),
            ): str,
            vol.Required(
                CONF_CODE_SLOTS,
                default=defaults.get(CONF_CODE_SLOTS, ""),
            ): str,
            vol.Required(
                CONF_PRIMARY_LOCK,
                default=defaults.get(CONF_PRIMARY_LOCK, ""),
            ): str,
            vol.Optional(
                CONF_NOTIFY_SERVICE,
                default=defaults.get(CONF_NOTIFY_SERVICE, ""),
            ): str,
            vol.Optional(
                CONF_LOCK_SERVICE_TYPE,
                default=defaults.get(CONF_LOCK_SERVICE_TYPE, LOCK_SERVICE_ZWAVE),
            ): vol.In(LOCK_SERVICE_OPTIONS),
            vol.Optional(
                CONF_CHECKIN_BUFFER_MINUTES,
                default=defaults.get(CONF_CHECKIN_BUFFER_MINUTES, DEFAULT_CHECKIN_BUFFER_MINUTES),
            ): vol.All(int, vol.Range(min=0, max=240)),
            vol.Optional(
                CONF_LOOKAHEAD_DAYS,
                default=defaults.get(CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD),
            ): vol.All(int, vol.Range(min=7, max=365)),
            vol.Optional(
                CONF_LOOKBACK_DAYS,
                default=defaults.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK),
            ): vol.All(int, vol.Range(min=0, max=90)),
        }
    )


class OwnerRezConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._creds: dict = {}

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 1: Collect and validate OwnerRez API credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_api(
                user_input[CONF_USERNAME],
                user_input[CONF_TOKEN],
                user_input[CONF_PROPERTY_ID],
            )
            if not errors:
                self._creds = user_input
                return await self.async_step_locks()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_TOKEN): str,
                vol.Required(CONF_PROPERTY_ID): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_locks(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Step 2: Collect lock entities and notification settings."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"OwnerRez — Property {self._creds[CONF_PROPERTY_ID]}",
                data={**self._creds, **user_input},
            )

        return self.async_show_form(
            step_id="locks",
            data_schema=_locks_schema({}),
            errors={},
        )

    async def _validate_api(
        self, username: str, token: str, property_id: str
    ) -> dict[str, str]:
        """Test credentials against the live OwnerRez API."""
        session = async_get_clientsession(self.hass)
        url = f"{API_BASE}/bookings?property_ids={property_id}&limit=1"
        auth = aiohttp.BasicAuth(username, token)
        try:
            async with session.get(
                url, auth=auth, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 401:
                    return {"base": "invalid_auth"}
                if resp.status not in (200, 204):
                    return {"base": "cannot_connect"}
        except aiohttp.ClientError:
            return {"base": "cannot_connect"}
        return {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OwnerRezOptionsFlow(config_entry)


class OwnerRezOptionsFlow(config_entries.OptionsFlow):
    """Allow reconfiguring lock / notification settings after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Pre-fill current values (options override data)
        current = {**self._config_entry.data, **self._config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=_locks_schema(current),
            errors={},
        )
