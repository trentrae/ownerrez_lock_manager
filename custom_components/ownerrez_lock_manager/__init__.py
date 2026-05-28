"""OwnerRez Lock Manager integration setup."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, PLATFORMS, SERVICE_ACTIVATE_EARLY, SERVICE_CLEAR_CODE, SERVICE_REFRESH
from .coordinator import OwnerRezCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OwnerRez Lock Manager from a config entry."""
    coordinator = OwnerRezCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register domain services.
    # Note: services are registered once per domain. For users with multiple
    # config entries (multiple properties), the last loaded entry's coordinator
    # handles these services. Per-entry service support can be added in a future
    # version if multi-property use cases require it.
    async def _activate_early(_call: ServiceCall) -> None:
        await coordinator.activate_code_early()

    async def _clear_code(_call: ServiceCall) -> None:
        await coordinator.clear_guest_code()

    async def _refresh(_call: ServiceCall) -> None:
        await coordinator.async_refresh()

    hass.services.async_register(DOMAIN, SERVICE_ACTIVATE_EARLY, _activate_early)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_CODE, _clear_code)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: OwnerRezCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_shutdown()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if not hass.data[DOMAIN]:
        for svc in (SERVICE_ACTIVATE_EARLY, SERVICE_CLEAR_CODE, SERVICE_REFRESH):
            hass.services.async_remove(DOMAIN, svc)

    return unloaded
