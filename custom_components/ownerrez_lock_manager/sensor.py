"""Sensor platform for OwnerRez Lock Manager.

Exposes the following entities (all under the "OwnerRez Lock Manager" device):

  sensor.ownerrez_next_booking        – next booking ID + full attributes
  sensor.ownerrez_locks_programmed    – count of programmed locks
  sensor.ownerrez_current_guest       – current guest name
  sensor.ownerrez_current_checkin     – check-in datetime (ISO string)
  sensor.ownerrez_current_checkout    – checkout datetime (ISO string)
  sensor.ownerrez_current_lock_code   – active door code (hidden by default)
  sensor.ownerrez_booking_status      – idle / booking_pending / code_active / guest_in
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OwnerRezCoordinator

_DEVICE_INFO_KEYS = ("identifiers", "name", "manufacturer", "model", "sw_version")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OwnerRezCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OwnerRezNextBookingSensor(coordinator, entry),
            OwnerRezLocksProgrammedSensor(coordinator, entry),
            OwnerRezCurrentGuestSensor(coordinator, entry),
            OwnerRezCheckinSensor(coordinator, entry),
            OwnerRezCheckoutSensor(coordinator, entry),
            OwnerRezLockCodeSensor(coordinator, entry),
            OwnerRezBookingStatusSensor(coordinator, entry),
        ]
    )


# ── Base class ────────────────────────────────────────────────────────────────

class _OwnerRezSensor(CoordinatorEntity[OwnerRezCoordinator], SensorEntity):
    """Shared base for all OwnerRez sensors."""

    def __init__(self, coordinator: OwnerRezCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OwnerRez Lock Manager",
            "manufacturer": "OwnerRez",
            "model": "Lock Manager",
            "sw_version": "2.0.0",
        }

    @property
    def _next_booking(self) -> dict | None:
        return (self.coordinator.data or {}).get("next_booking")


# ── Concrete sensors ──────────────────────────────────────────────────────────

class OwnerRezNextBookingSensor(_OwnerRezSensor):
    """Next booking ID with all booking details as attributes."""

    _attr_name = "OwnerRez Next Booking"
    _attr_icon = "mdi:calendar-clock"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_next_booking"

    @property
    def native_value(self) -> str:
        nb = self._next_booking
        return nb["id"] if nb else "none"

    @property
    def extra_state_attributes(self) -> dict:
        nb = self._next_booking
        if not nb:
            return {}
        return {
            "guest_name": nb.get("guest_name", ""),
            "arrival": nb.get("arrival", ""),
            "departure": nb.get("departure", ""),
            "check_in_time": nb.get("check_in_time", ""),
            "check_out_time": nb.get("check_out_time", ""),
            "door_code": nb.get("door_code", ""),
            "property_id": nb.get("property_id", ""),
            "status": nb.get("status", ""),
            "confirmation_code": nb.get("confirmation_code", ""),
        }


class OwnerRezLocksProgrammedSensor(_OwnerRezSensor):
    """Number of locks currently programmed with a guest code."""

    _attr_name = "OwnerRez Locks Programmed"
    _attr_icon = "mdi:lock-check"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_locks_programmed"

    @property
    def native_value(self) -> int:
        if not self.coordinator.code_active:
            return 0
        return len(self.coordinator.lock_entities)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "locks": self.coordinator.lock_entities if self.coordinator.code_active else [],
            "code_active": self.coordinator.code_active,
        }


class OwnerRezCurrentGuestSensor(_OwnerRezSensor):
    """Name of the currently active guest."""

    _attr_name = "OwnerRez Current Guest"
    _attr_icon = "mdi:account"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_current_guest"

    @property
    def native_value(self) -> str:
        return self.coordinator.current_guest_name or "none"


class OwnerRezCheckinSensor(_OwnerRezSensor):
    """Current guest check-in datetime (ISO 8601)."""

    _attr_name = "OwnerRez Current Check-in"
    _attr_icon = "mdi:calendar-arrow-right"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_current_checkin"

    @property
    def native_value(self) -> str:
        dt = self.coordinator.current_checkin
        return dt.isoformat() if dt else "none"


class OwnerRezCheckoutSensor(_OwnerRezSensor):
    """Current guest checkout datetime (ISO 8601)."""

    _attr_name = "OwnerRez Current Check-out"
    _attr_icon = "mdi:calendar-arrow-left"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_current_checkout"

    @property
    def native_value(self) -> str:
        dt = self.coordinator.current_checkout
        return dt.isoformat() if dt else "none"


class OwnerRezLockCodeSensor(_OwnerRezSensor):
    """Active door code — hidden from the default entity list for security."""

    _attr_name = "OwnerRez Current Lock Code"
    _attr_icon = "mdi:lock"
    _attr_entity_registry_visible_default = False

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_current_lock_code"

    @property
    def native_value(self) -> str:
        return self.coordinator.current_lock_code or "none"


class OwnerRezBookingStatusSensor(_OwnerRezSensor):
    """Overall status: idle / booking_pending / code_active / guest_in."""

    _attr_name = "OwnerRez Booking Status"
    _attr_icon = "mdi:home-clock"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_booking_status"

    @property
    def native_value(self) -> str:
        c = self.coordinator
        if c.code_active:
            return "guest_in" if c.guest_arrived else "code_active"
        if self._next_booking:
            return "booking_pending"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        c = self.coordinator
        return {
            "code_active": c.code_active,
            "guest_arrived": c.guest_arrived,
            "current_booking_id": c.current_booking_id,
        }
