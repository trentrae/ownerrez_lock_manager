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
from datetime import date, datetime, time, timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
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
    CONF_PRIMARY_LOCK,
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

        # ── Persistent runtime state ──────────────────────────────────────────
        self.code_active: bool = False
        self.guest_arrived: bool = False
        self.current_booking_id: str = ""
        self.current_guest_name: str = ""
        self.current_lock_code: str = ""
        self.current_checkin: datetime | None = None
        self.current_checkout: datetime | None = None

        # ── Scheduled-callback cancellers ─────────────────────────────────────
        self._cancel_checkin: Any = None
        self._cancel_checkout: Any = None
        self._cancel_24h_reminder: Any = None
        self._cancel_checkout_day: Any = None
        self._cancel_lock_listener: Any = None

    # ── Properties / helpers ─────────────────────────────────────────────────

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

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Load persisted state and register the lock listener."""
        stored: dict[str, Any] = await self._store.async_load() or {}

        self.code_active = stored.get("code_active", False)
        self.guest_arrived = stored.get("guest_arrived", False)
        self.current_booking_id = stored.get("current_booking_id", "")
        self.current_guest_name = stored.get("current_guest_name", "")
        self.current_lock_code = stored.get("current_lock_code", "")

        for key, attr in (("current_checkin", "current_checkin"), ("current_checkout", "current_checkout")):
            iso = stored.get(key)
            setattr(self, attr, dt_util.parse_datetime(iso) if iso else None)

        self._register_lock_listener()

    async def async_shutdown(self) -> None:
        """Cancel every scheduled callback."""
        for attr in (
            "_cancel_checkin",
            "_cancel_checkout",
            "_cancel_24h_reminder",
            "_cancel_checkout_day",
            "_cancel_lock_listener",
        ):
            canceller = getattr(self, attr)
            if canceller is not None:
                canceller()
            setattr(self, attr, None)

    # ── Data update ──────────────────────────────────────────────────────────

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
        next_booking = self._find_next_booking(bookings)

        # New booking detected → update state and schedule lock events
        if next_booking and str(next_booking["id"]) != self.current_booking_id:
            await self._sync_booking(next_booking)

        # Startup / post-checkout recovery check
        await self._check_current_state()

        return {"bookings": bookings, "next_booking": next_booking}

    # ── Booking processing ────────────────────────────────────────────────────

    def _find_next_booking(self, bookings: list[dict]) -> dict[str, Any] | None:
        """Return processed data for the earliest future-checkout active booking."""
        now_ts = dt_util.now().timestamp()
        valid: list[dict] = []

        for b in bookings:
            if b.get("type") != "booking" or b.get("status") != "active":
                continue
            departure = b.get("departure", "")
            check_out = b.get("check_out") or "10:00"
            raw_co = dt_util.parse_datetime(f"{departure}T{check_out}:00")
            if raw_co is None:
                continue
            co_ts = dt_util.as_utc(dt_util.as_local(raw_co)).timestamp()
            if co_ts <= now_ts:
                continue
            valid.append(b)

        if not valid:
            return None

        valid.sort(key=lambda b: b.get("arrival", ""))
        b = valid[0]

        arrival = b.get("arrival", "")
        check_in = b.get("check_in") or "16:00"
        departure = b.get("departure", "")
        check_out = b.get("check_out") or "10:00"

        guest = b.get("guest") or {}
        first = guest.get("first_name", "")
        last = guest.get("last_name", "")
        guest_name = f"{first} {last}".strip() or "Guest"

        door_codes: list[dict] = b.get("door_codes") or []
        door_code = door_codes[0].get("code", "") if door_codes else ""

        raw_ci = dt_util.parse_datetime(f"{arrival}T{check_in}:00")
        raw_co = dt_util.parse_datetime(f"{departure}T{check_out}:00")
        if raw_ci is None or raw_co is None:
            return None

        return {
            "id": str(b.get("id", "")),
            "guest_name": guest_name,
            "arrival": arrival,
            "departure": departure,
            "check_in_time": check_in,
            "check_out_time": check_out,
            "checkin_dt": dt_util.as_local(raw_ci),
            "checkout_dt": dt_util.as_local(raw_co),
            "door_code": door_code,
            "property_id": str(b.get("property_id", "")),
            "status": b.get("status", ""),
            "confirmation_code": b.get("platform_reservation_number", ""),
        }

    async def _sync_booking(self, booking: dict[str, Any]) -> None:
        """Store new booking data, reschedule callbacks, and notify."""
        self.current_booking_id = booking["id"]
        self.current_guest_name = booking["guest_name"]
        self.current_lock_code = booking["door_code"]
        self.current_checkin = booking["checkin_dt"]
        self.current_checkout = booking["checkout_dt"]
        await self._save_state()
        self._schedule_lock_events(booking)

        if booking["door_code"]:
            await self._notify_ha(
                "✅ OwnerRez Booking Synced",
                (
                    f"**Guest:** {booking['guest_name']}\n"
                    f"**Check-in:** {booking['arrival']} at {booking['check_in_time']}\n"
                    f"**Lock Code:** {booking['door_code']}\n\n"
                    f"Code will be programmed {self.checkin_buffer_minutes} minute(s) before check-in."
                ),
                "ownerrez_booking_sync",
            )

    # ── Scheduling ────────────────────────────────────────────────────────────

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

        # 24-hour reminder: 9 AM the day before check-in
        day_before = (checkin_dt - timedelta(hours=24)).date()
        remind_9am = dt_util.as_local(datetime.combine(day_before, time(9, 0, 0)))
        if remind_9am > now:
            self._cancel_24h_reminder = async_track_point_in_time(
                self.hass, self._on_24h_reminder, remind_9am
            )

        # Same-day checkout reminder: 8 AM on checkout day
        checkout_8am = dt_util.as_local(datetime.combine(checkout_dt.date(), time(8, 0, 0)))
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

    # ── Startup state recovery ────────────────────────────────────────────────

    async def _check_current_state(self) -> None:
        """On HA start / hourly refresh: verify lock state matches expectations."""
        now = dt_util.now()
        if not self.current_checkin or not self.current_checkout:
            return

        # Past checkout → clear if still marked active
        if now >= self.current_checkout:
            if self.code_active:
                _LOGGER.info("OwnerRez: Checkout has passed; clearing locks")
                await self._do_checkout()
            return

        # Within active window → program if not already active
        buffer = timedelta(minutes=self.checkin_buffer_minutes)
        if now >= (self.current_checkin - buffer) and not self.code_active and self.current_lock_code:
            _LOGGER.info("OwnerRez: Mid-stay detected on startup; programming locks")
            await self._do_checkin()

    # ── Lock operations ───────────────────────────────────────────────────────

    async def _do_checkin(self) -> None:
        """Program all configured locks with the guest code."""
        if self.code_active or not self.current_lock_code:
            return

        locks = self.lock_entities
        slots = self.code_slots
        svc = self.service_type
        count = min(len(locks), len(slots))

        for i in range(count):
            entity, slot = locks[i], slots[i]
            try:
                if svc == LOCK_SERVICE_ZWAVE:
                    await self.hass.services.async_call(
                        "zwave_js", "clear_lock_usercode",
                        {"entity_id": entity, "code_slot": slot},
                        blocking=True,
                    )
                    await asyncio.sleep(3)
                    await self.hass.services.async_call(
                        "zwave_js", "set_lock_usercode",
                        {"entity_id": entity, "code_slot": slot, "usercode": self.current_lock_code},
                        blocking=True,
                    )
                else:
                    await self.hass.services.async_call(
                        "lock", "set_usercode",
                        {"entity_id": entity, "code_slot": slot, "usercode": self.current_lock_code},
                        blocking=True,
                    )
                await asyncio.sleep(2)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("OwnerRez: Failed to program %s slot %s: %s", entity, slot, err)

        self.code_active = True
        self.guest_arrived = False
        await self._save_state()
        self.async_update_listeners()

        await self._notify_ha(
            "🔓 Guest Check-in Active",
            (
                f"**{self.current_guest_name}** can now check in.\n"
                f"Code **{self.current_lock_code}** programmed to {count} lock(s)."
            ),
            "ownerrez_checkin",
        )

    async def _do_checkout(self) -> None:
        """Clear guest code from all configured locks."""
        locks = self.lock_entities
        slots = self.code_slots
        svc = self.service_type
        count = min(len(locks), len(slots))
        guest = self.current_guest_name

        for i in range(count):
            entity, slot = locks[i], slots[i]
            try:
                if svc == LOCK_SERVICE_ZWAVE:
                    await self.hass.services.async_call(
                        "zwave_js", "clear_lock_usercode",
                        {"entity_id": entity, "code_slot": slot},
                        blocking=True,
                    )
                else:
                    await self.hass.services.async_call(
                        "lock", "clear_usercode",
                        {"entity_id": entity, "code_slot": slot},
                        blocking=True,
                    )
                await asyncio.sleep(2)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("OwnerRez: Failed to clear %s slot %s: %s", entity, slot, err)

        self.code_active = False
        self.guest_arrived = False
        self.current_guest_name = ""
        self.current_lock_code = ""
        self.current_booking_id = ""
        await self._save_state()
        self.async_update_listeners()

        await self._notify_ha(
            "✅ Guest Check-out Complete",
            f"**{guest}**'s code cleared from {count} lock(s).",
            "ownerrez_checkout",
        )

        # Immediately re-fetch so a same-day incoming guest is picked up
        self.hass.async_create_task(self.async_refresh())

    # ── Reminder notifications ────────────────────────────────────────────────

    async def _send_24h_reminder(self) -> None:
        if not self.current_guest_name:
            return
        await self._notify_ha(
            "📅 Guest Checking In Tomorrow",
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
            "🏁 Guest Checks Out Today",
            (
                f"**{self.current_guest_name}** checks out at {t}.\n"
                "Lock codes will be disabled automatically."
            ),
            "ownerrez_reminder_checkout",
        )

    # ── Lock listener / arrival handling ─────────────────────────────────────

    def _register_lock_listener(self) -> None:
        """Watch the primary lock entity for guest door-open events."""
        if self._cancel_lock_listener:
            self._cancel_lock_listener()
            self._cancel_lock_listener = None

        primary = self._cfg.get(CONF_PRIMARY_LOCK, "")
        if not primary:
            return

        @callback
        def _on_lock_change(entity_id: str, _old_state: Any, new_state: Any) -> None:
            if new_state is None or new_state.state != "unlocked":
                return
            if not self.code_active:
                return
            self.hass.async_create_task(self._handle_arrival(entity_id))

        self._cancel_lock_listener = async_track_state_change(
            self.hass, primary, _on_lock_change
        )

    async def _handle_arrival(self, entity_id: str) -> None:
        """Process a guest door-unlock event."""
        if entity_id not in self.lock_entities:
            return

        now = dt_util.now()
        state = self.hass.states.get(entity_id)
        friendly = state.attributes.get("friendly_name", entity_id) if state else entity_id
        notify_svc = self._cfg.get(CONF_NOTIFY_SERVICE, "")

        # Log every unlock to the HA logbook
        try:
            await self.hass.services.async_call(
                "logbook", "log",
                {
                    "name": f"{friendly} Guest Access",
                    "message": (
                        f"{self.current_guest_name} unlocked door using OwnerRez guest code"
                    ),
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
                "🔓 Door Activity",
                f"{self.current_guest_name} unlocked door\n\n🕐 {now.strftime('%I:%M:%S %p')}",
                {"tag": "door_unlock", "group": "guest_activity"},
            )

        # First-arrival notifications
        if not self.guest_arrived:
            self.guest_arrived = True
            await self._save_state()
            self.async_update_listeners()

            await self._notify_ha(
                "🚪 Guest Arrived",
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
                    f"🚪 {self.current_guest_name} Arrived",
                    (
                        f"Unlocked {friendly}\n\n"
                        f"🕐 {now.strftime('%I:%M:%S %p')}\n"
                        f"📅 {now.strftime('%A, %B %d, %Y')}"
                    ),
                    {
                        "notification_icon": "mdi:account-check",
                        "tag": "guest_first_arrival",
                        "group": "ownerrez",
                        "importance": "high",
                    },
                )

    # ── Manual actions (called by buttons / services) ─────────────────────────

    async def activate_code_early(self) -> None:
        """Manually activate guest code before the scheduled check-in time."""
        if not self.current_guest_name or not self.current_lock_code or self.code_active:
            _LOGGER.warning("OwnerRez: activate_code_early skipped — no pending booking or already active")
            return
        await self._do_checkin()

    async def clear_guest_code(self) -> None:
        """Manually clear the active guest code."""
        if not self.code_active:
            _LOGGER.warning("OwnerRez: clear_guest_code skipped — no active code")
            return
        await self._do_checkout()

    # ── Internal helpers ──────────────────────────────────────────────────────

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
            }
        )
