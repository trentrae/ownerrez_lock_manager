# OwnerRez Lock Manager for Home Assistant

**Version:** 2.0.1  
[![HACS][hacs-badge]][hacs-url]

Automatically manage smart lock codes for your vacation rental property by syncing booking data from OwnerRez. Lock codes are programmed a configurable number of minutes before guest check-in and automatically removed at checkout — all configured through the Home Assistant UI with no YAML editing required.

---

## Features

### 🔄 Automatic Synchronization
- Fetches booking data from OwnerRez API every hour
- Identifies the next upcoming booking automatically
- Syncs guest information, arrival/departure times, and door codes

### 🔐 Smart Lock Management
- Programs lock codes a configurable time before check-in (default: 5 minutes)
- Removes codes automatically at checkout time
- Supports multiple locks (front door, back door, garage, etc.)
- Uses door codes directly from OwnerRez (no code generation needed)
- Startup recovery: if HA restarts mid-stay, locks are re-programmed automatically

### 📱 Notifications
- Booking sync confirmations with guest details
- Check-in activation alerts
- Guest first-arrival detection (mobile push + HA notification)
- All door activity logged to HA logbook
- 24-hour advance check-in reminders
- Same-day checkout reminders
- Checkout completion confirmations

### 📊 Monitoring
- Seven sensor entities expose real-time booking and lock status
- Three button entities for manual control
- Three callable HA services

---

## Requirements

- **Home Assistant** 2024.1.0 or newer
- **HACS** (for managed installation and updates)
- **OwnerRez Account** with API access
- **Smart Locks** compatible with Home Assistant  
  - Z-Wave locks via the `zwave_js` integration (default)
  - Or any lock that supports the `lock.set_usercode` / `lock.clear_usercode` services

---

## Installation via HACS (Recommended for v2.0.1+)

### Step 1: Add the Custom Repository in HACS

1. Open **HACS** in your Home Assistant sidebar
2. Click the three-dot menu (⋮) in the top-right corner
3. Select **Custom repositories**
4. Paste `https://github.com/trentrae/Ownerrez_Lock_Manager` in the URL field
5. Select **Integration** as the category
6. Click **Add**

### Step 2: Install the Integration

1. Search for **OwnerRez Lock Manager** in HACS → Integrations
2. Open it and install the latest release (**v2.0.1**)
3. **Restart Home Assistant**

### Step 3: Add the Integration via UI

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **OwnerRez Lock Manager**
3. **Step 1 — Credentials:** Enter your OwnerRez email, API token (`pt_...`), and Property ID
   - Your token is under **OwnerRez → Settings → API**
   - Your Property ID is in the URL when viewing a property
4. **Step 2 — Locks:** Configure your lock entities and options (see below)
5. Click **Submit** — credentials are validated against the live API before saving

### Step 4: Get Future Updates

When a new version is released, HACS will show an update badge. Click **Update** in HACS and restart HA — no YAML files to touch.

> Already on v2.0.0? Updating to **v2.0.1** is in-place through HACS and does not require re-adding the integration.

---

## Configuration Reference

All settings are entered through the UI. No `secrets.yaml` or package YAML files are needed.

| Field | Description | Example |
|-------|-------------|---------|
| **OwnerRez Email** | Your OwnerRez login email | `you@example.com` |
| **API Token** | Token from OwnerRez → Settings → API | `pt_abc123...` |
| **Property ID** | Numeric ID from the OwnerRez property URL | `386633` |
| **Lock Entities** | Select your lock entities from Home Assistant | `lock.front_door, lock.back_door` |
| **Code Slots** | Code slot number for each lock (same order) | `5,5` |
| **Primary Lock** | Select the main lock used for arrival detection | `lock.front_door` |
| **Mobile Notify Target** | Optional notify target selected from Home Assistant | `notify.mobile_app_iphone` |
| **Lock Service Type** | `zwave_js` (default) or `lock` | `zwave_js` |
| **Check-in Buffer Minutes** | Minutes before check-in to activate code | `5` |
| **Lookahead Days** | How many days ahead to fetch bookings | `90` |
| **Lookback Days** | How many days back to fetch bookings | `7` |

To change any setting after setup: **Settings → Devices & Services → OwnerRez Lock Manager → Configure**

---

## Entities Created

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.ownerrez_next_booking` | Next booking ID with full details as attributes |
| `sensor.ownerrez_locks_programmed` | Number of locks currently programmed |
| `sensor.ownerrez_current_guest` | Current guest name |
| `sensor.ownerrez_current_checkin` | Current check-in datetime |
| `sensor.ownerrez_current_checkout` | Current checkout datetime |
| `sensor.ownerrez_current_lock_code` | Active door code *(hidden by default)* |
| `sensor.ownerrez_booking_status` | `idle` / `booking_pending` / `code_active` / `guest_in` |

### Buttons

| Entity | Action |
|--------|--------|
| `button.ownerrez_activate_guest_code_early` | Program locks immediately |
| `button.ownerrez_clear_guest_code` | Clear locks and reset booking state |
| `button.ownerrez_refresh_bookings` | Force API refresh now |

### Services

| Service | Description |
|---------|-------------|
| `ownerrez_lock_manager.activate_code_early` | Same as the button |
| `ownerrez_lock_manager.clear_guest_code` | Same as the button |
| `ownerrez_lock_manager.refresh_bookings` | Same as the button |

---

## Dashboard Cards

### Booking Status Card

```yaml
type: entities
title: Current Booking
entities:
  - entity: sensor.ownerrez_booking_status
    name: Status
  - entity: sensor.ownerrez_current_guest
    name: Guest Name
  - entity: sensor.ownerrez_current_checkin
    name: Check-in
  - entity: sensor.ownerrez_current_checkout
    name: Check-out
  - entity: sensor.ownerrez_locks_programmed
    name: Locks Programmed
```

### Next Booking Card

```yaml
type: entities
title: Next Booking
entities:
  - entity: sensor.ownerrez_next_booking
    name: Booking ID
  - type: attribute
    entity: sensor.ownerrez_next_booking
    attribute: guest_name
    name: Guest
  - type: attribute
    entity: sensor.ownerrez_next_booking
    attribute: arrival
    name: Arrival Date
  - type: attribute
    entity: sensor.ownerrez_next_booking
    attribute: check_in_time
    name: Check-in Time
  - type: attribute
    entity: sensor.ownerrez_next_booking
    attribute: door_code
    name: Door Code
```

### Manual Controls Card

```yaml
type: entities
title: Manual Controls
entities:
  - entity: button.ownerrez_activate_guest_code_early
  - entity: button.ownerrez_clear_guest_code
  - entity: button.ownerrez_refresh_bookings
```

---

## How It Works

### 1. Data Retrieval
Every hour, the integration queries the OwnerRez API to fetch bookings in a rolling window (configurable lookback + lookahead). Data is also refreshed on HA startup.

### 2. Booking Selection
The next booking is selected by:
- Filtering for `type: booking` and `status: active`
- Filtering out bookings whose **checkout datetime** (date + `check_out` time) has already passed
- Sorting by arrival date and selecting the earliest

### 3. Lock Programming
A point-in-time callback is registered for `(check-in time − buffer)`. When it fires:
- Each configured lock has its code slot cleared then set with the OwnerRez door code
- State is persisted to HA storage (survives restarts)

### 4. Checkout
A point-in-time callback is registered for the exact checkout datetime. When it fires:
- Each configured lock has its code slot cleared
- State is reset and persisted
- A fresh API fetch runs immediately (to catch same-day incoming guests)

### 5. Startup Recovery
On every HA start and hourly refresh, the integration checks whether the current time falls within an expected active window. If locks should be programmed but aren't (e.g., after an unexpected HA restart), they are programmed automatically.

### 6. Guest Arrival Detection
The primary lock entity is watched for state changes to `unlocked` while a guest code is active:
- **Every unlock** → logbook entry + mobile door-activity notification (if configured)
- **First unlock** → HA persistent notification + mobile first-arrival notification

---

## Troubleshooting

### No Booking Data
1. Go to **Settings → Devices & Services → OwnerRez Lock Manager**
2. Check `sensor.ownerrez_next_booking` — if state is `unavailable`, check HA logs
3. Use **Developer Tools → Services → `ownerrez_lock_manager.refresh_bookings`** to force a refresh
4. Verify API credentials via **Configure** on the integration page

### Locks Not Programming
1. Confirm your lock entity IDs exist: **Developer Tools → States**, search for `lock.`
2. Test manually: **Developer Tools → Services → `zwave_js.set_lock_usercode`** with your entity + slot
3. Check HA logs for `OwnerRez:` prefixed messages
4. Verify a door code is assigned to the booking in OwnerRez (**Booking → Arrival tab**)

### Codes Not Clearing at Checkout
1. Check `sensor.ownerrez_booking_status` — if it's still `code_active` after checkout time, press **Clear Guest Code** button
2. Check HA logs for any service-call errors on the lock entities

### API Errors
- **401 Unauthorized** → Regenerate your API token in OwnerRez → Settings → API
- **Connection error** → Check HA internet access; OwnerRez API base: `https://api.ownerrez.com/v2`

---

## Migrating from the YAML Package Version

If you previously used `ownerrez_lock_manager.yaml` in your `/config/packages/` folder:

1. Install this integration via HACS and configure it through the UI
2. Remove (or comment out) the `!include_dir_named packages` line from `configuration.yaml` if this was the only package, **OR** simply delete `/config/packages/ownerrez_lock_manager.yaml`
3. Remove the OwnerRez-related lines from `secrets.yaml` (they are no longer needed)
4. Restart Home Assistant
5. Update any dashboard cards to use the new entity IDs listed above

---

## Security Notes

- API credentials are stored in HA's encrypted config entry storage — not in plain-text YAML files
- The door code sensor (`sensor.ownerrez_current_lock_code`) is hidden from the entity list by default
- Credentials never leave your network except for direct calls to `api.ownerrez.com`
- Door codes are cleared from locks at checkout and from HA state after checkout

---

## Changelog

### v2.0.1
- Installation/upgrade instructions updated for the current HACS flow

### v2.0.0
- Full rewrite as a proper Python custom component
- HACS-managed installation and one-click updates
- All configuration via Home Assistant UI (no YAML editing)
- Startup recovery: auto-programs locks if HA restarts mid-stay
- Persistent state via HA storage (survives restarts)
- Point-in-time callbacks replace minute-by-minute polling for efficiency
- Added `sensor.ownerrez_booking_status` for easy automations/dashboards
- Added options flow for reconfiguring without reinstalling
- Same-day check-in/check-out handled correctly (immediate API refresh post-checkout)

### v1.3.3
- Fixed same-day checkout/check-in booking sensor datetime filter
- Force REST sensor refresh after checkout

### v1.3.2
- Updated to modern Home Assistant automation syntax

### v1.2.0
- Fixed duplicate YAML key errors
- Removed code generation (uses OwnerRez codes only)

### v1.0.0
- Initial release

---

## Support & Contributing

- **Issues:** [GitHub Issues](https://github.com/trentrae/Ownerrez_Lock_Manager/issues)
- **OwnerRez:** https://www.ownerrez.com
- **Home Assistant:** https://www.home-assistant.io

---

## License

Provided as-is for personal use. Modify and adapt as needed for your specific setup.

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://hacs.xyz
