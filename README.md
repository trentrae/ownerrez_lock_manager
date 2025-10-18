# OwnerRez Lock Manager for Home Assistant

**Version:** 1.2.0 (Optimized)

Automatically manage smart lock codes for your vacation rental property by syncing booking data from OwnerRez. Lock codes are programmed 5 minutes before guest check-in and automatically removed at checkout.

---

## Features

### 🔄 Automatic Synchronization
- Fetches booking data from OwnerRez API every hour
- Identifies the next upcoming booking automatically
- Syncs guest information, arrival/departure times, and door codes

### 🔐 Smart Lock Management
- Programs lock codes **5 minutes before check-in time**
- Removes codes automatically at checkout time
- Supports multiple locks (front door, back door, garage, etc.)
- Uses door codes directly from OwnerRez (no code generation)

### 📱 Notifications
- Booking sync confirmations with guest details
- Check-in activation alerts (5 min early)
- Guest arrival detection when locks are used
- 24-hour advance check-in reminders
- Same-day checkout reminders
- Checkout completion confirmations

### 📊 Monitoring
- Real-time view of active booking information
- Track which locks are currently programmed
- View guest name, dates, confirmation codes, and door codes
- Monitor booking status and property information

---

## Requirements

- **Home Assistant** 2023.1 or newer
- **OwnerRez Account** with API access
- **Smart Locks** compatible with Home Assistant that support the `lock.set_usercode` service (e.g., Z-Wave, Zigbee locks)
- **OwnerRez API Credentials** (username and API token)

---

## Installation

### Step 1: Get OwnerRez API Credentials

1. Log into your OwnerRez account
2. Navigate to **Settings → API**
3. Generate a new API token (starts with `pt_`)
4. Copy your email and token - you'll need these next

### Step 2: Add Credentials to Home Assistant

1. Open your Home Assistant configuration directory
2. Edit the `secrets.yaml` file
3. Add the following lines:

```yaml
ownerrez_username: "your-email@example.com"
ownerrez_token: "pt_your_token_here"
```

4. Save the file

### Step 3: Enable Packages (if not already enabled)

1. Edit your `configuration.yaml` file
2. Add or verify this section exists:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

3. Save the file

### Step 4: Create Packages Directory

If it doesn't exist, create a `packages` folder in your config directory:

```
/config/
  ├── configuration.yaml
  ├── secrets.yaml
  └── packages/
      └── (this is where the lock manager file goes)
```

### Step 5: Install Lock Manager File

1. Download `ownerrez_lock_manager.yaml`
2. Place it in `/config/packages/`
3. The full path should be: `/config/packages/ownerrez_lock_manager.yaml`

### Step 6: Customize Configuration

Open `ownerrez_lock_manager.yaml` and customize these sections:

#### A. Property ID (Line ~26)
```yaml
input_text:
  ownerrez_property_ids:
    initial: "445458"  # ← Change to YOUR property ID
```

Find your property ID in OwnerRez under Settings → Properties.

#### B. Lock Entities (Line ~35)
```yaml
  ownerrez_lock_entities:
    initial: "lock.front_door,lock.back_door,lock.garage_door"  # ← Change to YOUR lock entity IDs
```

Use comma-separated entity IDs from your Home Assistant locks.

#### C. Code Slots (Line ~39)
```yaml
  ownerrez_lock_code_slots:
    initial: "5,5,5"  # ← Slot numbers for each lock (must match number of locks)
```

Specify which user code slot to use on each lock. Example:
- If you have 3 locks, use 3 numbers: `"5,5,5"`
- If you have 2 locks, use 2 numbers: `"5,5"`

#### D. API Date Range (Line ~78)
```yaml
rest:
  - resource: "https://api.ownerrez.com/v2/bookings?property_ids=445458&limit=20&from=2025-10-14&to=2026-04-14&include_door_codes=true&include_guest=true"
```

Change:
- `property_ids=445458` to your property ID
- `from=2025-10-14` to today's date minus a few days
- `to=2026-04-14` to ~90-180 days in the future

**Note:** The system will auto-update these dates, but you must manually update the REST resource URL and restart HA for changes to take effect.

### Step 7: Restart Home Assistant

1. Go to **Settings → System → Restart**
2. Wait for Home Assistant to fully restart
3. Check for any error messages in the logs

---

## Configuration

### Date Range Management

The system automatically tracks bookings within a configurable date range:

- **Lookback Days** (default: 7) - How many days in the past to check
- **Lookahead Days** (default: 90) - How many days in the future to check

These settings update automatically at 1 AM on the first of each month, but **you must manually update the REST API URL** (line ~78) and restart Home Assistant for changes to take effect.

### Lock Code Timing

- **Enable:** 5 minutes before check-in time
- **Disable:** At exact checkout time
- **Check Frequency:** Every minute

### Notification Settings

By default, the system uses `persistent_notification` which creates notifications in the Home Assistant UI. To send to mobile devices:

1. Replace `persistent_notification.create` with `notify.mobile_app_YOUR_DEVICE`
2. Or use notification groups for multiple devices

---

## Usage

### Dashboard Cards

Add these to your dashboard to monitor the system:

#### Guest Information Card
```yaml
type: entities
title: Current Booking
entities:
  - entity: input_text.ownerrez_current_guest_name
    name: Guest Name
  - entity: input_datetime.ownerrez_current_checkin
    name: Check-in
  - entity: input_datetime.ownerrez_current_checkout
    name: Check-out
  - entity: input_text.ownerrez_current_lock_code
    name: Lock Code
  - entity: input_boolean.ownerrez_lock_code_active
    name: Code Active
```

#### Lock Status Card
```yaml
type: entities
title: Lock Status
entities:
  - entity: sensor.ownerrez_locks_programmed
    name: Locks Programmed
  - entity: lock.front_door
  - entity: lock.back_door
  - entity: lock.garage_door
```

#### Next Booking Card
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
    name: Arrival
  - type: attribute
    entity: sensor.ownerrez_next_booking
    attribute: departure
    name: Departure
  - type: attribute
    entity: sensor.ownerrez_next_booking
    attribute: door_code
    name: Door Code
```

---

## How It Works

### 1. Data Retrieval
Every hour, Home Assistant queries the OwnerRez API to fetch:
- Active bookings
- Guest information (first name, last name)
- Arrival and departure dates/times
- Door codes assigned in OwnerRez
- Confirmation numbers

### 2. Booking Selection
The system identifies the "next booking" by:
- Filtering for `type: booking` and `status: active`
- Excluding bookings with past departure dates
- Sorting by arrival date and selecting the earliest

### 3. Data Sync
When a new booking is detected or at 6 AM daily:
- Guest information is stored in input helpers
- Check-in/checkout times are set
- Door code from OwnerRez is saved
- A notification confirms the sync

### 4. Lock Programming
**5 minutes before check-in time:**
- All configured locks are programmed with the guest's door code
- Each lock receives the code in its assigned slot
- The `ownerrez_lock_code_active` boolean turns ON
- A notification confirms activation

### 5. Checkout
**At checkout time:**
- All configured locks have the guest code removed
- The `ownerrez_lock_code_active` boolean turns OFF
- Guest information is cleared
- A notification confirms removal

### 6. Guest Detection
When any configured lock is unlocked:
- If a code is currently active
- A notification is sent showing which guest unlocked which door

---

## Troubleshooting

### No Booking Data Showing

**Check the API Connection:**
1. Go to **Developer Tools → States**
2. Find `sensor.ownerrez_bookings_raw`
3. Check if it has `items` in attributes

**If no items:**
- Verify credentials in `secrets.yaml`
- Check the REST resource URL has correct property ID
- Verify date range includes upcoming bookings
- Check OwnerRez API token is valid

**Test API manually:**
```bash
curl -u "your-email@example.com:pt_your_token" \
  "https://api.ownerrez.com/v2/bookings?property_ids=YOUR_ID&limit=5&include_door_codes=true&include_guest=true"
```

### Next Booking Shows "none"

**Verify booking filters:**
1. Check `sensor.ownerrez_next_booking` state
2. Ensure bookings are:
   - Type: `booking` (not `quote` or `inquiry`)
   - Status: `active` (not `cancelled` or `tentative`)
   - Departure date: Today or future

**Check OwnerRez booking status:**
- Log into OwnerRez
- Verify the booking is confirmed and active
- Check that it's assigned to the correct property

### Lock Codes Not Programming

**Check timing:**
- Codes only program 5 minutes before check-in
- Monitor automation traces in **Settings → Automations & Scenes → OwnerRez: Enable Lock Code at Check-in**

**Verify lock compatibility:**
- Test manually: `Developer Tools → Services`
- Service: `lock.set_usercode`
- Entity: Your lock
- Data: `{ "code_slot": 5, "usercode": "123456" }`

**Check code slots:**
- Ensure slots match your lock's available user code slots
- Some locks reserve slots 1-3 for master codes
- Try slots 4-10 for guest codes

**View automation logs:**
```
Settings → System → Logs
Filter for: ownerrez
```

### Codes Not Clearing at Checkout

**Check automation:**
1. **Settings → Automations & Scenes**
2. Find **OwnerRez: Disable Lock Code at Check-out**
3. Click the automation → **⋮ Menu → Traces**
4. See if it's running at checkout time

**Common issues:**
- Checkout time hasn't passed yet
- `input_boolean.ownerrez_lock_code_active` is already OFF
- Lock service not responding

### No Notifications Received

**Persistent Notifications:**
- Check the notification bell icon in Home Assistant UI
- Persistent notifications appear there, not on mobile

**For mobile notifications:**
1. Replace `persistent_notification.create` with `notify.mobile_app_YOUR_DEVICE`
2. Find your device name: **Settings → Devices & Services → Mobile App**
3. Update all automations that send notifications

### API Errors in Logs

**"401 Unauthorized":**
- Check credentials in `secrets.yaml`
- Verify API token starts with `pt_`
- Regenerate token in OwnerRez if needed

**"Range too big" Error:**
- Fixed in v1.2.0
- Update to latest version

**"Template Error":**
- Check that all entity IDs in lock_entities exist
- Verify input helpers are created
- Restart Home Assistant after making changes

### Duplicate Key Errors

**"YAML contains duplicate key":**
- Fixed in v1.2.0
- All `input_text` entries are now consolidated
- Delete old file and use updated version

### Door Code Missing from OwnerRez

The system **requires** door codes to be assigned in OwnerRez. If a booking doesn't have a code:

1. Log into OwnerRez
2. Open the booking
3. Go to the **Arrival** tab
4. Add a door code
5. Wait for next sync (or restart HA)

**To auto-generate codes in OwnerRez:**
- OwnerRez can auto-generate codes for you
- Configure in **Settings → Properties → [Your Property] → Door Locks**

---

## Entities Created

### Sensors
- `sensor.ownerrez_bookings_raw` - Raw API data
- `sensor.ownerrez_next_booking` - Next booking details
- `sensor.ownerrez_locks_programmed` - Count of programmed locks

### Input Helpers
- `input_text.ownerrez_property_ids` - Property ID(s)
- `input_text.ownerrez_lock_entities` - Lock entity IDs
- `input_text.ownerrez_lock_code_slots` - Code slot numbers
- `input_text.ownerrez_current_guest_name` - Active guest name
- `input_text.ownerrez_current_lock_code` - Active door code
- `input_text.ownerrez_current_booking_id` - Active booking ID
- `input_datetime.ownerrez_current_checkin` - Check-in time
- `input_datetime.ownerrez_current_checkout` - Checkout time
- `input_boolean.ownerrez_lock_code_active` - Code status
- `input_number.ownerrez_lookback_days` - Past days to check
- `input_number.ownerrez_lookahead_days` - Future days to check

### Buttons
- `input_button.ownerrez_update_date_range` - Manually update date range

### Automations
- `ownerrez_update_api_date_range` - Auto-update tracking dates
- `ownerrez_sync_booking_data` - Sync booking information
- `ownerrez_enable_lock_code_checkin` - Program codes at check-in
- `ownerrez_disable_lock_code_checkout` - Remove codes at checkout
- `ownerrez_guest_arrival_notification` - Alert on door unlock
- `ownerrez_checkin_reminder_24h` - 24-hour advance reminder
- `ownerrez_checkout_reminder_today` - Same-day checkout reminder

---

## Advanced Configuration

### Multiple Properties

To manage multiple properties, duplicate the package file and customize each:

1. Copy `ownerrez_lock_manager.yaml` to `ownerrez_lock_manager_property2.yaml`
2. Change all entity `unique_id` values to avoid conflicts
3. Update property ID and lock entities
4. Restart Home Assistant

### Custom Check-in Buffer

To change when codes are programmed (default: 5 minutes early):

Find line ~325:
```yaml
{{ checkin is not none and now_time >= (checkin - 300) and now_time < (checkin - 240) }}
```

Change `300` (seconds) to your desired buffer:
- 10 minutes early: `600`
- 15 minutes early: `900`
- 30 minutes early: `1800`
- 1 hour early: `3600`

### Extended Checkout Grace Period

To give guests extra time after checkout (e.g., 1 hour grace period):

Find line ~365:
```yaml
{{ checkout is not none and now_time >= checkout and now_time < (checkout + 60) }}
```

Change `checkout` to `(checkout + 3600)` for 1 hour grace period.

---

## Security Considerations

### Best Practices

1. **Use dedicated code slots** - Don't use slots 1-3 (often reserved for master codes)
2. **Unique codes per booking** - OwnerRez can auto-generate unique codes
3. **Regular audits** - Periodically check that codes are being cleared
4. **Backup access** - Always maintain a separate master code
5. **Monitor logs** - Watch for failed programming attempts

### API Security

- Store credentials only in `secrets.yaml`
- Never commit `secrets.yaml` to version control
- Regenerate API tokens periodically
- Use read-only API tokens if possible (OwnerRez may support this)

### Privacy

The system stores:
- Guest first and last names (in input helpers)
- Door codes (password-protected input helper)
- Booking IDs and dates

This data is:
- Stored locally in Home Assistant
- Cleared after checkout
- Not transmitted outside your network (except to OwnerRez API)

---

## Support & Contributing

### Getting Help

1. Check this README thoroughly
2. Review Home Assistant logs for errors
3. Test API connection manually
4. Check OwnerRez booking status and codes

### Reporting Issues

When reporting issues, include:
- Home Assistant version
- Lock brand/model
- Relevant log entries
- Configuration (remove sensitive data)

### Future Enhancements

Potential features for future versions:
- Multiple property support in single package
- Slack/Discord notification integration
- Cleaning schedule integration
- Guest messaging automation
- Booking statistics and reporting

---

## Changelog

### v1.2.0 (Current - Optimized)
- Fixed duplicate YAML key errors
- Removed code generation (uses OwnerRez codes only)
- Consolidated all input_text entries
- Optimized template sensors for better performance
- Improved error handling and logging
- Standardized attribute naming conventions
- Enhanced documentation

### v1.1.0
- Added guest name extraction from API
- Included door code support
- Added debug sensors for troubleshooting

### v1.0.0
- Initial release
- Basic booking sync
- Lock code automation
- Notification system

---

## License

This integration is provided as-is for personal use. Modify and adapt as needed for your specific setup.

---

## Credits

Created for vacation rental property managers using OwnerRez and Home Assistant.

**OwnerRez:** https://www.ownerrez.com  
**Home Assistant:** https://www.home-assistant.io
