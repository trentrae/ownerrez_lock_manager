"""Binary sensor platform for OwnerRez Lock Manager.

Exposes the following entities (all under the "OwnerRez Lock Manager" device):

  binary_sensor.ownerrez_same_day_checkin  – On when today is a check-in day
"""
from __future__ import annotations

from datetime import date

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, VERSION
from .coordinator import OwnerRezCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OwnerRezCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OwnerRezSameDayCheckinBinarySensor(coordinator, entry),
            OwnerRezGuestArrivedBinarySensor(coordinator, entry),
            OwnerRezAllLocksProgrammedBinarySensor(coordinator, entry),
        ]
    )


class OwnerRezSameDayCheckinBinarySensor(
    CoordinatorEntity[OwnerRezCoordinator], BinarySensorEntity
):
    """Binary sensor that is On when today is a guest check-in day.

    The sensor turns On if the next upcoming booking's arrival date matches
    today's local date.  It remains On for the entire calendar day so it can
    be used to trigger dashboard highlights, automations, or notifications.
    """

    _attr_name = "OwnerRez Same-Day Check-in"
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: OwnerRezCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_same_day_checkin"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OwnerRez Lock Manager",
            "manufacturer": "OwnerRez",
            "model": "Lock Manager",
            "sw_version": VERSION,
        }

    @property
    def is_on(self) -> bool:
        """Return True when today is the arrival date of the next booking."""
        next_booking: dict | None = (self.coordinator.data or {}).get("next_booking")
        if not next_booking:
            return False
        arrival: str = next_booking.get("arrival", "")
        if not arrival:
            return False
        today = dt_util.now().date()
        try:
            arrival_date = date.fromisoformat(arrival)
        except ValueError:
            return False
        return arrival_date == today

    @property
    def extra_state_attributes(self) -> dict:
        next_booking: dict | None = (self.coordinator.data or {}).get("next_booking")
        if not next_booking:
            return {}
        checkin_dt = next_booking.get("checkin_dt")
        return {
            "guest_name": next_booking.get("guest_name", ""),
            "arrival": next_booking.get("arrival", ""),
            "check_in_time": next_booking.get("check_in_time", ""),
            "checkin_datetime": checkin_dt.isoformat() if checkin_dt else None,
        }


class OwnerRezGuestArrivedBinarySensor(
    CoordinatorEntity[OwnerRezCoordinator], BinarySensorEntity
):
    """Binary sensor that is On when the current guest has arrived."""

    _attr_name = "OwnerRez Guest Arrived"
    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: OwnerRezCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_guest_arrived"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OwnerRez Lock Manager",
            "manufacturer": "OwnerRez",
            "model": "Lock Manager",
            "sw_version": VERSION,
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.guest_arrived

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "current_guest_name": self.coordinator.current_guest_name,
            "current_booking_id": self.coordinator.current_booking_id,
            "code_active": self.coordinator.code_active,
        }


class OwnerRezAllLocksProgrammedBinarySensor(
    CoordinatorEntity[OwnerRezCoordinator], BinarySensorEntity
):
    """Binary sensor that is On when all configured lock slots are programmed."""

    _attr_name = "OwnerRez All Locks Programmed"
    _attr_icon = "mdi:lock-check-outline"

    def __init__(self, coordinator: OwnerRezCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_all_locks_programmed"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OwnerRez Lock Manager",
            "manufacturer": "OwnerRez",
            "model": "Lock Manager",
            "sw_version": VERSION,
        }

    @property
    def is_on(self) -> bool:
        status = self.coordinator.get_lock_programming_status()
        total = status.get("total", 0)
        return bool(total > 0 and status.get("programmed", 0) == total)

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.get_lock_programming_status()
        return {
            "programmed_locks": status.get("programmed", 0),
            "total_locks": status.get("total", 0),
            "details": status.get("details", []),
        }
