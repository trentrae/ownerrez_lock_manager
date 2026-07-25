"""DataUpdateCoordinator for OwnerRez Lock Manager.

Handles:
  - Hourly API polling from OwnerRez
  - Next-booking selection (filter active, future-checkout, sort by arrival)
  - Persistent state across HA restarts (HA Store)
  - Point-in-time callbacks for check-in activation and checkout clearing
  - Daily reminder notifications (24 h before check-in, 8 AM on checkout day)
  - Lock state listener for guest arrival detection
  - Manual early-activation and clear-code actions
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    API_BASE,
    CONF_CHECKIN_BUFFER_MINUTES,
    CONF_CODE_SLOTS,
    CONF_LOCK_ENTITIES,
    CONF_LOCK_SERVICE_TYPE,
    CONF_LOOKBACK_DAYS,
    CONF_LOOKAHEAD_DAYS,
    CONF_NOTIFY_SERVICE,
    CONF_PROPERTY_ID,
    CONF_TOKEN,
    CONF_USERNAME,
    DEFAULT_CHECKIN_BUFFER_MINUTES,
    DEFAULT_LOOKBACK,
    DEFAULT_LOOKAHEAD,
    DOMAIN,
    LOCK_SERVICE_LOCK,
    LOCK_SERVICE_ZWAVE,
    POLL_INTERVAL_SECONDS,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_SETTLE_DELAY_SECONDS = 2
_PROGRAM_VERIFY_DELAY_SECONDS = 5
_LOCK_RETRY_ATTEMPTS = 3
_POST_CHECKOUT_VERIFY_ATTEMPTS = 5
_POST_CHECKOUT_VERIFY_INTERVAL_SECONDS = 120


class OwnerRezCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages OwnerRez data, lock programming, and all automation logic."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
        )
        self._entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

        # ΓöÇΓöÇ Persistent runtime state ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        self.code_active: bool = False
        self.guest_arrived: bool = False
        self.current_booking_id: str = ""
        self.current_guest_name: str = ""
        self.current_lock_code: str = ""
        self.current_checkin: datetime | None = None
        self.current_checkout: datetime | None = None
        self.next_booking: dict[str, Any] | None = None
        self._lock_device_ids: dict[str, str] = {}
        self._recent_unlock_slots: dict[str, dict[str, Any]] = {}
        self._recent_slot_states: dict[str, dict[int, dict[str, Any]]] = {}

        # ΓöÇΓöÇ Scheduled-callback cancellers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        self._cancel_checkin: Any = None
        self._cancel_checkout: Any = None
        self._cancel_24h_reminder: Any = None
        self._cancel_checkout_day: Any = None
        self._cancel_lock_listener: Any = None
        self._cancel_zwave_listener: Any = None

    # ΓöÇΓöÇ Properties / helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    @property
    def _cfg(self) -> dict[str, Any]:
        """Merge data and options so options always win."""
        return {**self._entry.data, **self._entry.options}

    @property
    def lock_entities(self) -> list[str]:
        return [e.strip() for e in self._cfg[CONF_LOCK_ENTITIES].split(",") if e.strip()]

    @property
    def code_slots(self) -> list[int]:
        return [int(s.strip()) for s in self._cfg[CONF_CODE_SLOTS].split(",") if s.strip()]

    @property
    def checkin_buffer_minutes(self) -> int:
        return int(self._cfg.get(CONF_CHECKIN_BUFFER_MINUTES, DEFAULT_CHECKIN_BUFFER_MINUTES))

    @property
    def service_type(self) -> str:
        return self._cfg.get(CONF_LOCK_SERVICE_TYPE, LOCK_SERVICE_ZWAVE)

    # ΓöÇΓöÇ Lifecycle ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    async def async_setup(self) -> None:
        """Load persisted state and register the lock listener."""
        stored: dict[str, Any] = await self._store.async_load() or {}

        self.code_active = stored.get("code_active", False)
        self.guest_arrived = stored.get("guest_arrived", False)
        self.current_booking_id = stored.get("current_booking_id", "")
        self.current_guest_name = stored.get("current_guest_name", "")
        self.current_lock_code = stored.get("current_lock_code", "")

        for key in ("current_checkin", "current_checkout"):
            iso = stored.get(key)
            setattr(self, key, dt_util.parse_datetime(iso) if iso else None)
        self.next_booking = self._restore_booking(stored.get("next_booking"))

        self._register_lock_listener()

    async def async_shutdown(self) -> None:
        """Cancel every scheduled callback."""
        for attr in (
            "_cancel_checkin",
            "_cancel_checkout",
            "_cancel_24h_reminder",
            "_cancel_checkout_day",
            "_cancel_lock_listener",
            "_cancel_zwave_listener",
        ):
            canceller = getattr(self, attr)
            if canceller is not None:
                canceller()
            setattr(self, attr, None)

    # ΓöÇΓöÇ Data update ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch bookings from OwnerRez and process state."""
        cfg = self._cfg
        lookahead = int(cfg.get(CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD))
        lookback = int(cfg.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK))

        now = dt_util.now()
        from_date = (now - timedelta(days=lookback)).strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=lookahead)).strftime("%Y-%m-%d")

        url = (
            f"{API_BASE}/bookings"
            f"?property_ids={cfg[CONF_PROPERTY_ID]}"
            f"&limit=20&from={from_date}&to={to_date}"
            f"&include_door_codes=true&include_guest=true"
        )

        session = async_get_clientsession(self.hass)
        auth = aiohttp.BasicAuth(cfg[CONF_USERNAME], cfg[CONF_TOKEN])

        try:
            async with session.get(url, auth=auth, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 401:
                    raise UpdateFailed("OwnerRez API: invalid credentials (401)")
                if resp.status != 200:
                    raise UpdateFailed(f"OwnerRez API: HTTP {resp.status}")
                raw = await resp.json()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"OwnerRez API connection error: {err}") from err

        bookings: list[dict] = raw.get("items", [])
        current_booking, next_booking = self._select_bookings(bookings)

        # Never switch to a future booking while the current stored stay window
        # has not reached checkout yet.
        now_local = dt_util.now()
        if (
            self.current_booking_id
            and self.current_checkout
            and now_local < self.current_checkout
            and (
                current_booking is None
                or current_booking.get("id") != self.current_booking_id
            )
        ):
            _LOGGER.warning(
                "OwnerRez: Ignoring booking switch to %s before checkout; "
                "keeping current booking %s active until %s",
                current_booking.get("id") if current_booking else "none",
                self.current_booking_id,
                self.current_checkout,
            )
            current_booking = None

        # New booking detected ΓåÆ update state and schedule lock events
        if current_booking and not self._same_booking(current_booking):
            await self._sync_booking(current_booking)
        self.next_booking = next_booking
        await self._save_state()

        # Startup / post-checkout recovery check
        await self._check_current_state()

        return {
            "bookings": bookings,
            "next_booking": self._display_next_booking(current_booking, next_booking),
        }

    # ΓöÇΓöÇ Booking processing ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _normalize_booking(self, b: dict[str, Any]) -> dict[str, Any] | None:
        """Return normalized booking data or None when the booking is unusable."""
        if b.get("type") != "booking" or b.get("status") != "active":
            return None

        arrival = b.get("arrival", "")
        check_in = b.get("check_in") or "16:00"
        departure = b.get("departure", "")
        check_out = b.get("check_out") or "10:00"
        raw_ci = dt_util.parse_datetime(f"{arrival}T{check_in}:00")
        raw_co = dt_util.parse_datetime(f"{departure}T{check_out}:00")
        if raw_ci is None or raw_co is None:
            return None

        checkin_dt = dt_util.as_local(raw_ci)
        checkout_dt = dt_util.as_local(raw_co)
        if checkout_dt.timestamp() <= dt_util.now().timestamp():
            return None

        guest = b.get("guest") or {}
        first = guest.get("first_name", "")
        last = guest.get("last_name", "")
        guest_name = f"{first} {last}".strip() or "Guest"

        door_codes: list[dict] = b.get("door_codes") or []
        door_code = door_codes[0].get("code", "") if door_codes else ""

        return {
            "id": str(b.get("id", "")),
            "guest_name": guest_name,
            "arrival": arrival,
            "departure": departure,
            "check_in_time": check_in,
            "check_out_time": check_out,
            "checkin_dt": checkin_dt,
            "checkout_dt": checkout_dt,
            "door_code": door_code,
            "property_id": str(b.get("property_id", "")),
            "status": b.get("status", ""),
            "confirmation_code": b.get("platform_reservation_number", ""),
        }

    def _select_bookings(
        self, bookings: list[dict]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Return the operational booking and the next arriving booking."""
        now_ts = dt_util.now().timestamp()
        valid: list[dict[str, Any]] = []

        for b in bookings:
            normalized = self._normalize_booking(b)
            if normalized:
                valid.append(normalized)

        if not valid:
            return None, None

        valid.sort(key=lambda booking: booking["checkin_dt"])
        active_booking = next(
            (
                booking
                for booking in valid
                if booking["checkin_dt"].timestamp() <= now_ts < booking["checkout_dt"].timestamp()
            ),
            None,
        )
        upcoming_booking = next(
            (booking for booking in valid if booking["checkin_dt"].timestamp() > now_ts),
            None,
        )
        return active_booking or upcoming_booking, upcoming_booking

    def _display_next_booking(
        self,
        current_booking: dict[str, Any] | None,
        next_booking: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Return the booking to expose as the next arriving guest."""
        if next_booking:
            return next_booking
        if current_booking and current_booking["checkin_dt"] > dt_util.now():
            return current_booking
        return None

    def _same_booking(self, booking: dict[str, Any]) -> bool:
        """Return True when the normalized booking matches stored current state."""
        return (
            booking["id"] == self.current_booking_id
            and booking["guest_name"] == self.current_guest_name
            and booking["door_code"] == self.current_lock_code
            and booking["checkin_dt"] == self.current_checkin
            and booking["checkout_dt"] == self.current_checkout
        )

    def _restore_booking(self, booking: dict[str, Any] | None) -> dict[str, Any] | None:
        """Restore a persisted booking dict."""
        if not booking:
            return None
        restored = dict(booking)
        for key in ("checkin_dt", "checkout_dt"):
            iso = restored.get(key)
            restored[key] = dt_util.parse_datetime(iso) if iso else None
        if not restored.get("id") or not restored.get("checkin_dt") or not restored.get("checkout_dt"):
            return None
        return restored

    def _serialize_booking(self, booking: dict[str, Any] | None) -> dict[str, Any] | None:
        """Serialize a booking dict for HA storage."""
        if not booking:
            return None
        serialized = dict(booking)
        for key in ("checkin_dt", "checkout_dt"):
            dt_value = serialized.get(key)
            serialized[key] = dt_value.isoformat() if dt_value else None
        return serialized

    async def _sync_booking(self, booking: dict[str, Any], notify: bool = True) -> None:
        """Store new booking data, reschedule callbacks, and notify."""
        self.current_booking_id = booking["id"]
        self.current_guest_name = booking["guest_name"]
        self.current_lock_code = booking["door_code"]
        self.current_checkin = booking["checkin_dt"]
        self.current_checkout = booking["checkout_dt"]
        await self._save_state()
        self._schedule_lock_events(booking)
        self.async_update_listeners()

        if notify and booking["door_code"]:
            await self._notify_ha(
                "OwnerRez Booking Synced",
                (
                    f"**Guest:** {booking['guest_name']}\n"
                    f"**Check-in:** {booking['arrival']} at {booking['check_in_time']}\n"
                    f"**Lock Code:** {booking['door_code']}\n\n"
                    f"Code will be programmed {self.checkin_buffer_minutes} minute(s) before check-in."
                ),
                "ownerrez_booking_sync",
            )

    # ΓöÇΓöÇ Scheduling ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _cancel_timers(self) -> None:
        for attr in ("_cancel_checkin", "_cancel_checkout", "_cancel_24h_reminder", "_cancel_checkout_day"):
            fn = getattr(self, attr)
            if fn is not None:
                fn()
            setattr(self, attr, None)

    def _schedule_lock_events(self, booking: dict[str, Any]) -> None:
        """Register point-in-time callbacks for check-in, checkout, and reminders."""
        self._cancel_timers()

        now = dt_util.now()
        checkin_dt: datetime = booking["checkin_dt"]
        checkout_dt: datetime = booking["checkout_dt"]
        buffer = timedelta(minutes=self.checkin_buffer_minutes)
        checkin_trigger = checkin_dt - buffer

        if checkin_trigger > now:
            self._cancel_checkin = async_track_point_in_time(
                self.hass, self._on_checkin_time, checkin_trigger
            )
            _LOGGER.debug("OwnerRez: Check-in timer set for %s", checkin_trigger)

        if checkout_dt > now:
            self._cancel_checkout = async_track_point_in_time(
                self.hass, self._on_checkout_time, checkout_dt
            )
            _LOGGER.debug("OwnerRez: Checkout timer set for %s", checkout_dt)

        # 24-hour reminder: 9 AM the calendar day before check-in
        # Use date arithmetic (not timedelta(hours=24)) to handle DST correctly
        day_before = checkin_dt.date() - timedelta(days=1)
        remind_9am = checkin_dt.replace(
            year=day_before.year, month=day_before.month, day=day_before.day,
            hour=9, minute=0, second=0, microsecond=0,
        )
        if remind_9am > now:
            self._cancel_24h_reminder = async_track_point_in_time(
                self.hass, self._on_24h_reminder, remind_9am
            )

        # Same-day checkout reminder: 8 AM on checkout day (preserves checkout_dt timezone)
        checkout_8am = checkout_dt.replace(hour=8, minute=0, second=0, microsecond=0)
        if checkout_8am > now:
            self._cancel_checkout_day = async_track_point_in_time(
                self.hass, self._on_checkout_day_reminder, checkout_8am
            )

    @callback
    def _on_checkin_time(self, _now: datetime) -> None:
        self.hass.async_create_task(self._do_checkin())

    @callback
    def _on_checkout_time(self, _now: datetime) -> None:
        self.hass.async_create_task(self._do_checkout())

    @callback
    def _on_24h_reminder(self, _now: datetime) -> None:
        self.hass.async_create_task(self._send_24h_reminder())

    @callback
    def _on_checkout_day_reminder(self, _now: datetime) -> None:
        self.hass.async_create_task(self._send_checkout_day_reminder())

    # ΓöÇΓöÇ Startup state recovery ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    async def _check_current_state(self) -> None:
        """On HA start / hourly refresh: verify lock state matches expectations."""
        now = dt_util.now()
        if not self.current_checkin or not self.current_checkout:
            return

        # Past checkout ΓåÆ clear if still marked active
        if now >= self.current_checkout:
            if self.code_active:
                _LOGGER.info("OwnerRez: Checkout has passed; clearing locks")
                await self._do_checkout()
            return

        # Within active window ΓåÆ program if not already active
        buffer = timedelta(minutes=self.checkin_buffer_minutes)
        if now >= (self.current_checkin - buffer) and not self.code_active and self.current_lock_code:
            _LOGGER.info("OwnerRez: Mid-stay detected on startup; programming locks")
            await self._do_checkin()

    # ΓöÇΓöÇ Lock operations ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    async def _do_checkin(self) -> None:
        """Program all configured locks with the guest code."""
        if self.code_active or not self.current_lock_code:
            return

        locks = self.lock_entities
        slots = self.code_slots
        count = min(len(locks), len(slots))
        success_count = 0

        for i in range(count):
            entity, slot = locks[i], slots[i]
            try:
                programmed = await self._program_lock_slot(entity, slot, self.current_lock_code)
                if programmed:
                    success_count += 1
                else:
                    _LOGGER.warning(
                        "OwnerRez: Lock %s slot %s did not verify as programmed after retries",
                        entity,
                        slot,
                    )
                # Small gap between consecutive locks to avoid flooding the mesh
                if i < count - 1:
                    await asyncio.sleep(1)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("OwnerRez: Failed to program %s slot %s: %s", entity, slot, err)

        self.code_active = success_count > 0
        self.guest_arrived = False
        await self._save_state()
        self.async_update_listeners()

        await self._notify_ha(
            "Guest Check-in Active",
            (
                f"**{self.current_guest_name}** can now check in.\n"
                f"Code **{self.current_lock_code}** verified on {success_count}/{count} lock(s)."
            ),
            "ownerrez_checkin",
        )

    async def _do_checkout(self, *, clear_booking_state: bool = True, promote_next: bool = True) -> None:
        """Clear guest code from all configured locks."""
        locks = self.lock_entities
        slots = self.code_slots
        count = min(len(locks), len(slots))
        guest = self.current_guest_name
        cleared_count = 0

        for i in range(count):
            entity, slot = locks[i], slots[i]
            try:
                cleared = await self._clear_lock_slot(entity, slot)
                if cleared:
                    cleared_count += 1
                else:
                    _LOGGER.warning(
                        "OwnerRez: Lock %s slot %s did not verify as cleared after retries",
                        entity,
                        slot,
                    )
                if i < count - 1:
                    await asyncio.sleep(1)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("OwnerRez: Failed to clear %s slot %s: %s", entity, slot, err)

        self.code_active = False
        self.guest_arrived = False

        if clear_booking_state:
            self.current_guest_name = ""
            self.current_lock_code = ""
            self.current_booking_id = ""
            self.current_checkin = None
            self.current_checkout = None

        await self._save_state()
        self.async_update_listeners()

        await self._notify_ha(
            "Guest Check-out Complete",
            f"**{guest}**'s code verified cleared on {cleared_count}/{count} lock(s).",
            "ownerrez_checkout",
        )

        # Continue validating clears for a short window after checkout because
        # some locks apply slot changes slowly over Z-Wave/Zigbee meshes.
        self.hass.async_create_task(self._post_checkout_verification())

        if clear_booking_state and promote_next and self.next_booking:
            promoted_booking = self.next_booking
            self.next_booking = None
            await self._sync_booking(promoted_booking, notify=False)
            self.async_set_updated_data(
                {
                    "bookings": (self.data or {}).get("bookings", []),
                    "next_booking": None,
                }
            )

        # Immediately re-fetch so a same-day incoming guest is picked up.
        if clear_booking_state:
            self.hass.async_create_task(self.async_refresh())

    # ΓöÇΓöÇ Reminder notifications ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    async def _send_24h_reminder(self) -> None:
        if not self.current_guest_name:
            return
        await self._notify_ha(
            "Guest Checking In Tomorrow",
            (
                f"**{self.current_guest_name}** checks in tomorrow.\n"
                f"Code: **{self.current_lock_code}**"
            ),
            "ownerrez_reminder_checkin",
        )

    async def _send_checkout_day_reminder(self) -> None:
        if not self.code_active or not self.current_checkout:
            return
        t = self.current_checkout.strftime("%I:%M %p")
        await self._notify_ha(
            "Guest Checks Out Today",
            (
                f"**{self.current_guest_name}** checks out at {t}.\n"
                "Lock codes will be disabled automatically."
            ),
            "ownerrez_reminder_checkout",
        )

    # ΓöÇΓöÇ Lock listener / arrival handling ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _register_lock_listener(self) -> None:
        """Watch all configured lock entities for guest door-open events."""
        if self._cancel_lock_listener:
            self._cancel_lock_listener()
            self._cancel_lock_listener = None
        if self._cancel_zwave_listener:
            self._cancel_zwave_listener()
            self._cancel_zwave_listener = None

        watch_entities = [entity_id for entity_id in self.lock_entities if entity_id]
        if not watch_entities:
            return

        entity_reg = er.async_get(self.hass)
        self._lock_device_ids = {}
        for entity_id in watch_entities:
            entry = entity_reg.async_get(entity_id)
            if entry and entry.device_id:
                self._lock_device_ids[entry.device_id] = entity_id

        @callback
        def _on_lock_change(entity_id: str, _old_state: Any, new_state: Any) -> None:
            if new_state is None or new_state.state != "unlocked":
                return
            if not self.code_active:
                return
            self.hass.async_create_task(self._handle_arrival(entity_id))

        self._cancel_lock_listener = async_track_state_change(
            self.hass, watch_entities, _on_lock_change
        )

        if self.service_type == LOCK_SERVICE_ZWAVE:
            @callback
            def _on_zwave_notification(event: Event) -> None:
                device_id = event.data.get("device_id")
                parameters = event.data.get("parameters") or {}
                raw_slot = parameters.get("userId") or parameters.get("user_id")
                event_label = str(event.data.get("event_label") or "")
                property_key_name = str(event.data.get("property_key_name") or "")
                if not device_id or raw_slot in (None, ""):
                    return
                entity_id = self._lock_device_ids.get(device_id)
                if not entity_id:
                    return
                try:
                    slot = int(raw_slot)
                except (TypeError, ValueError):
                    return

                label = f"{event_label} {property_key_name}".lower()

                if any(word in label for word in ("unlock", "open")):
                    self._recent_unlock_slots[entity_id] = {
                        "slot": slot,
                        "seen_at": dt_util.now(),
                    }

                if any(word in label for word in ("code", "usercode", "user code", "slot")):
                    if any(word in label for word in ("clear", "delete", "remove")):
                        self._set_recent_slot_state(entity_id, slot, "available")
                    elif any(word in label for word in ("set", "program", "add", "write")):
                        self._set_recent_slot_state(entity_id, slot, "programmed")

            self._cancel_zwave_listener = self.hass.bus.async_listen(
                "zwave_js_notification", _on_zwave_notification
            )

    def _set_recent_slot_state(self, entity_id: str, slot: int, state: str) -> None:
        """Cache most recent known slot state for Z-Wave-first health reporting."""
        self._recent_slot_states.setdefault(entity_id, {})[slot] = {
            "state": state,
            "seen_at": dt_util.now(),
        }

    def _recent_slot_state(
        self,
        entity_id: str,
        slot: int,
        max_age: timedelta = timedelta(seconds=600),
    ) -> str | None:
        """Return a fresh cached slot state when available."""
        cached = self._recent_slot_states.get(entity_id, {}).get(slot)
        if not cached:
            return None
        if (dt_util.now() - cached["seen_at"]) > max_age:
            return None
        value = str(cached.get("state") or "").strip().lower()
        return value or None

    def _expected_guest_slot(self, entity_id: str) -> int | None:
        """Return the configured guest slot for a lock entity."""
        try:
            index = self.lock_entities.index(entity_id)
            return self.code_slots[index]
        except (ValueError, IndexError):
            return None

    def _resolve_unlock_actor(self, entity_id: str) -> tuple[str, bool]:
        """Return a human-friendly unlock actor label and whether it was the guest code."""
        state = self.hass.states.get(entity_id)
        attrs = state.attributes if state else {}
        expected_slot = self._expected_guest_slot(entity_id)

        actor = next(
            (
                str(attrs[key]).strip()
                for key in (
                    "changed_by",
                    "changed_by_name",
                    "changed_by_user",
                    "last_unlocked_by",
                )
                if attrs.get(key)
            ),
            "",
        )

        raw_slot = next(
            (
                attrs.get(key)
                for key in ("code_slot", "user_id", "userId", "slot")
                if attrs.get(key) not in (None, "", "unknown", "unavailable")
            ),
            None,
        )
        if raw_slot in (None, ""):
            recent = self._recent_unlock_slots.get(entity_id)
            if recent and (dt_util.now() - recent["seen_at"]) <= timedelta(seconds=15):
                raw_slot = recent["slot"]

        slot: int | None = None
        if raw_slot not in (None, ""):
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                slot = None

        if actor and slot is not None:
            return f"{actor} (slot {slot})", expected_slot == slot
        if actor:
            guest_name = self.current_guest_name.casefold()
            return actor, bool(guest_name and guest_name in actor.casefold())
        if slot is not None:
            if expected_slot == slot:
                return f"{self.current_guest_name} (slot {slot})", True
            return f"User slot {slot}", False
        if self.service_type == LOCK_SERVICE_ZWAVE:
            return "Unknown user", False
        return self.current_guest_name or "Unknown user", bool(self.current_guest_name)

    async def _handle_arrival(self, entity_id: str) -> None:
        """Process a guest door-unlock event."""
        if entity_id not in self.lock_entities:
            return

        now = dt_util.now()
        state = self.hass.states.get(entity_id)
        friendly = state.attributes.get("friendly_name", entity_id) if state else entity_id
        notify_svc = self._cfg.get(CONF_NOTIFY_SERVICE, "")
        actor, used_guest_code = self._resolve_unlock_actor(entity_id)
        activity_message = (
            f"{actor} unlocked door using the OwnerRez guest slot"
            if used_guest_code
            else f"{actor} unlocked door using a different lock user/slot"
        )

        # Log every unlock to the HA logbook
        try:
            await self.hass.services.async_call(
                "logbook", "log",
                {
                    "name": f"{friendly} Access",
                    "message": activity_message,
                    "entity_id": entity_id,
                    "domain": "lock",
                },
            )
        except Exception:  # noqa: BLE001
            pass

        # Mobile door-activity notification (every unlock)
        if notify_svc:
            await self._send_mobile(
                notify_svc,
                "Door Activity",
                f"{actor} unlocked door\n\nTime: {now.strftime('%I:%M:%S %p')}",
                {"tag": "door_unlock", "group": "guest_activity"},
            )

        # First-arrival notifications
        if used_guest_code and not self.guest_arrived:
            self.guest_arrived = True
            await self._save_state()
            self.async_update_listeners()

            await self._notify_ha(
                "Guest Arrived",
                (
                    f"**{self.current_guest_name}** unlocked {friendly}.\n\n"
                    f"**Time:** {now.strftime('%I:%M %p')}\n"
                    f"**Date:** {now.strftime('%A, %B %d, %Y')}"
                ),
                "ownerrez_first_arrival",
            )

            if notify_svc:
                await self._send_mobile(
                    notify_svc,
                    f"{self.current_guest_name} Arrived",
                    (
                        f"Unlocked {friendly}\n\n"
                        f"Time: {now.strftime('%I:%M:%S %p')}\n"
                        f"Date: {now.strftime('%A, %B %d, %Y')}"
                    ),
                    {
                        "notification_icon": "mdi:account-check",
                        "tag": "guest_first_arrival",
                        "group": "ownerrez",
                        "importance": "high",
                    },
                )

    # ΓöÇΓöÇ Manual actions (called by buttons / services) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    async def activate_code_early(self) -> None:
        """Manually activate guest code before the scheduled check-in time."""
        if not self.current_guest_name or not self.current_lock_code or self.code_active:
            _LOGGER.warning("OwnerRez: activate_code_early skipped - no pending booking or already active")
            return
        await self._do_checkin()

    async def clear_guest_code(self) -> None:
        """Manually clear the active guest code."""
        if not self.code_active:
            _LOGGER.warning("OwnerRez: clear_guest_code skipped - no active code")
            return

        now_local = dt_util.now()
        active_stay = bool(
            self.current_checkin
            and self.current_checkout
            and self.current_checkin <= now_local < self.current_checkout
        )

        if active_stay:
            _LOGGER.info(
                "OwnerRez: Manual clear during active stay for booking %s; preserving current booking state",
                self.current_booking_id,
            )
            await self._do_checkout(clear_booking_state=False, promote_next=False)
            return

        await self._do_checkout()

    # ΓöÇΓöÇ Internal helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    async def _notify_ha(self, title: str, message: str, notification_id: str) -> None:
        """Create a persistent notification in Home Assistant."""
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {"title": title, "message": message, "notification_id": notification_id},
        )

    async def _send_mobile(self, service: str, title: str, message: str, data: dict) -> None:
        """Send a mobile push notification via the configured notify service."""
        try:
            domain, name = service.split(".", 1)
            await self.hass.services.async_call(
                domain, name,
                {"title": title, "message": message, "data": data},
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("OwnerRez: Mobile notification failed (%s): %s", service, err)

    async def _save_state(self) -> None:
        """Persist coordinator state to HA storage so it survives restarts."""
        await self._store.async_save(
            {
                "code_active": self.code_active,
                "guest_arrived": self.guest_arrived,
                "current_booking_id": self.current_booking_id,
                "current_guest_name": self.current_guest_name,
                "current_lock_code": self.current_lock_code,
                "current_checkin": (
                    self.current_checkin.isoformat() if self.current_checkin else None
                ),
                "current_checkout": (
                    self.current_checkout.isoformat() if self.current_checkout else None
                ),
                "next_booking": self._serialize_booking(self.next_booking),
            }
        )

    def _slot_state(self, entity_id: str, slot: int) -> str:
        """Return the raw slot status string for a lock slot."""
        if self.service_type == LOCK_SERVICE_ZWAVE:
            cached = self._recent_slot_state(entity_id, slot)
            if cached:
                return cached

        state = self.hass.states.get(entity_id)
        if not state:
            return "unknown"
        attrs = state.attributes

        for key in (
            f"code_slot_{slot}",
            f"usercode_slot_{slot}",
            f"user_code_slot_{slot}",
            f"slot_{slot}",
        ):
            raw = attrs.get(key)
            if raw is not None:
                return str(raw).strip().lower()

        slot_map = attrs.get("code_slots") or attrs.get("usercode_slots")
        if isinstance(slot_map, dict):
            raw = slot_map.get(str(slot))
            if raw is not None:
                return str(raw).strip().lower()

        return "unknown"

    def _slot_is_cleared(self, entity_id: str, slot: int) -> bool:
        """Return True when a lock slot appears empty/available."""
        return self._slot_state(entity_id, slot) in {"available", "empty", "none", ""}

    def _slot_is_programmed(self, entity_id: str, slot: int) -> bool:
        """Return True when a lock slot appears occupied/programmed."""
        slot_state = self._slot_state(entity_id, slot)
        return slot_state not in {"available", "empty", "none", "", "unknown", "unavailable"}

    async def _program_lock_slot(self, entity_id: str, slot: int, code: str) -> bool:
        """Program a lock slot with retries and post-write verification."""
        for attempt in range(1, _LOCK_RETRY_ATTEMPTS + 1):
            self._set_recent_slot_state(entity_id, slot, "available")
            if self.service_type == LOCK_SERVICE_ZWAVE:
                await self.hass.services.async_call(
                    "zwave_js",
                    "clear_lock_usercode",
                    {"entity_id": entity_id, "code_slot": slot},
                    blocking=True,
                )
                await asyncio.sleep(_SETTLE_DELAY_SECONDS)
                await self.hass.services.async_call(
                    "zwave_js",
                    "set_lock_usercode",
                    {"entity_id": entity_id, "code_slot": slot, "usercode": code},
                    blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    "lock",
                    "clear_usercode",
                    {"entity_id": entity_id, "code_slot": slot},
                    blocking=True,
                )
                await asyncio.sleep(_SETTLE_DELAY_SECONDS)
                await self.hass.services.async_call(
                    "lock",
                    "set_usercode",
                    {"entity_id": entity_id, "code_slot": slot, "usercode": code},
                    blocking=True,
                )

            self._set_recent_slot_state(entity_id, slot, "programmed")

            await asyncio.sleep(_PROGRAM_VERIFY_DELAY_SECONDS)
            if self._slot_is_programmed(entity_id, slot):
                return True

            # Generic lock integrations may not expose per-slot attributes.
            if self.service_type == LOCK_SERVICE_LOCK and self._slot_state(entity_id, slot) in {
                "unknown",
                "unavailable",
            }:
                return True

            _LOGGER.debug(
                "OwnerRez: Program verify failed for %s slot %s on attempt %s/%s (state=%s)",
                entity_id,
                slot,
                attempt,
                _LOCK_RETRY_ATTEMPTS,
                self._slot_state(entity_id, slot),
            )

        return False

    async def _clear_lock_slot(self, entity_id: str, slot: int) -> bool:
        """Clear a lock slot with retries and post-write verification."""
        for attempt in range(1, _LOCK_RETRY_ATTEMPTS + 1):
            self._set_recent_slot_state(entity_id, slot, "programmed")
            if self.service_type == LOCK_SERVICE_ZWAVE:
                await self.hass.services.async_call(
                    "zwave_js",
                    "clear_lock_usercode",
                    {"entity_id": entity_id, "code_slot": slot},
                    blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    "lock",
                    "clear_usercode",
                    {"entity_id": entity_id, "code_slot": slot},
                    blocking=True,
                )

            self._set_recent_slot_state(entity_id, slot, "available")

            await asyncio.sleep(_SETTLE_DELAY_SECONDS)
            if self._slot_is_cleared(entity_id, slot):
                return True

            # Generic lock integrations may not expose per-slot attributes.
            if self.service_type == LOCK_SERVICE_LOCK and self._slot_state(entity_id, slot) in {
                "unknown",
                "unavailable",
            }:
                return True

            _LOGGER.debug(
                "OwnerRez: Clear verify failed for %s slot %s on attempt %s/%s (state=%s)",
                entity_id,
                slot,
                attempt,
                _LOCK_RETRY_ATTEMPTS,
                self._slot_state(entity_id, slot),
            )

        return False

    def get_lock_programming_status(self) -> dict[str, Any]:
        """Return per-lock slot verification data for dashboard sensors."""
        locks = self.lock_entities
        slots = self.code_slots
        count = min(len(locks), len(slots))

        details: list[dict[str, Any]] = []
        programmed = 0
        cleared = 0
        unknown = 0

        for idx in range(count):
            entity_id = locks[idx]
            slot = slots[idx]
            slot_state = self._slot_state(entity_id, slot)

            status = "unknown"
            if self._slot_is_programmed(entity_id, slot):
                status = "programmed"
                programmed += 1
            elif self._slot_is_cleared(entity_id, slot):
                status = "cleared"
                cleared += 1
            elif self.service_type == LOCK_SERVICE_ZWAVE and not self.code_active:
                # If no guest code is active and slot telemetry is missing,
                # present idle slots as cleared rather than unknown.
                status = "cleared"
                cleared += 1
            else:
                unknown += 1

            details.append(
                {
                    "entity_id": entity_id,
                    "slot": slot,
                    "status": status,
                    "raw_slot_state": slot_state,
                }
            )

        return {
            "total": count,
            "programmed": programmed,
            "cleared": cleared,
            "unknown": unknown,
            "details": details,
        }

    async def _post_checkout_verification(self) -> None:
        """Retry clear operations for a short time window after checkout."""
        for _ in range(_POST_CHECKOUT_VERIFY_ATTEMPTS):
            if self.code_active:
                return

            status = self.get_lock_programming_status()
            if status["total"] == 0 or status["cleared"] == status["total"]:
                return

            for lock in status["details"]:
                if lock["status"] != "cleared":
                    await self._clear_lock_slot(lock["entity_id"], int(lock["slot"]))

            self.async_update_listeners()
            await asyncio.sleep(_POST_CHECKOUT_VERIFY_INTERVAL_SECONDS)
