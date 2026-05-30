"""Button platform for OwnerRez Lock Manager.

  button.ownerrez_activate_guest_code_early  – program locks right now
  button.ownerrez_clear_guest_code           – manually clear locks
  button.ownerrez_refresh_bookings           – force API refresh
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OwnerRezCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OwnerRezCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OwnerRezActivateEarlyButton(coordinator, entry),
            OwnerRezClearCodeButton(coordinator, entry),
            OwnerRezRefreshButton(coordinator, entry),
        ]
    )


class _OwnerRezButton(ButtonEntity):
    """Shared base for OwnerRez buttons."""

    def __init__(self, coordinator: OwnerRezCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OwnerRez Lock Manager",
        }


class OwnerRezActivateEarlyButton(_OwnerRezButton):
    """Activate the guest door code right now (before scheduled time)."""

    _attr_name = "OwnerRez Activate Guest Code Early"
    _attr_icon = "mdi:lock-clock"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_activate_early"

    async def async_press(self) -> None:
        await self._coordinator.activate_code_early()


class OwnerRezClearCodeButton(_OwnerRezButton):
    """Clear the active guest code from all locks immediately."""

    _attr_name = "OwnerRez Clear Guest Code"
    _attr_icon = "mdi:lock-remove"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_clear_code"

    async def async_press(self) -> None:
        await self._coordinator.clear_guest_code()


class OwnerRezRefreshButton(_OwnerRezButton):
    """Force an immediate refresh of booking data from OwnerRez."""

    _attr_name = "OwnerRez Refresh Bookings"
    _attr_icon = "mdi:refresh"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_refresh"

    async def async_press(self) -> None:
        await self._coordinator.async_refresh()
