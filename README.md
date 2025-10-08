# OwnerRez Lock Manager for Home Assistant

Automatically sync your OwnerRez bookings with Home Assistant and manage smart lock codes for seamless guest check-ins and check-outs.

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Compatible-41BDF5.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

✨ **Automatic Booking Sync** - Pulls upcoming reservations from OwnerRez API every hour  
🔐 **Smart Lock Integration** - Automatically generates and manages temporary lock codes  
📅 **Scheduled Access** - Enables codes at check-in, disables at check-out  
📱 **Rich Notifications** - Alerts for bookings, arrivals, and reminders  
👤 **Guest Tracking** - Know exactly who's checking in and when  
🔔 **Proactive Reminders** - 24-hour check-in and same-day check-out alerts  

## Prerequisites

- Home Assistant (2023.1 or newer recommended)
- OwnerRez account with API access
- Compatible smart lock (Z-Wave, Zigbee, or Wi-Fi)
- Mobile app or notification service configured in Home Assistant

## Supported Lock Types

This integration works with any lock that supports the Home Assistant `lock.set_usercode` service:

- **Z-Wave Locks**: Kwikset, Schlage, Yale (via Z-Wave JS)
- **Zigbee Locks**: Yale, Schlage Encode (via ZHA or Zigbee2MQTT)
- **Wi-Fi Locks**: August, Wyze Lock (via native integrations)

## Installation

### Step 1: Get OwnerRez API Credentials

1. Log into your [OwnerRez account](https://app.ownerrez.com)
2. Navigate to **Settings** → **Security** → **Personal Access Tokens**
3. Click **Create Personal Access Token**
4. Give it a name (e.g., "Home Assistant") and click **Create**
5. Copy your token (you won't be able to see it again!)

### Step 2: Enable Packages in Home Assistant

Edit your `/config/configuration.yaml` and add:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

### Step 3: Add Credentials to Secrets

Edit `/config/secrets.yaml` and add:

```yaml
ownerrez_username: "your-email@example.com"
ownerrez_token: "pt_your_token_here"
```

### Step 4: Install the Package

1. Create a `packages` folder in your `/config/` directory if it doesn't exist
2. Download `ownerrez_lock_manager.yaml` from this repository
3. Place it in `/config/packages/ownerrez_lock_manager.yaml`
4. Edit the file to customize your settings (see Configuration section)

### Step 5: Restart Home Assistant

1. Go to **Developer Tools** → **YAML** → **Check Configuration**
2. If valid, go to **Settings** → **System** → **Restart**

## Configuration

### Required Changes

Open `/config/packages/ownerrez_lock_manager.yaml` and update:

**1. Lock Entity ID** (line ~115, 180, 228):
```yaml
entity_id: lock.front_door  # Change to YOUR lock entity
```

**2. Notification Service** (line ~127, 148, 193, 248, etc.):
```yaml
service: notify.mobile_app  # Change to YOUR notification service
# Examples: notify.mobile_app_iphone, notify.alexa_media, notify.smtp
```

**3. Code Slot** (line ~117, 182):
```yaml
code_slot: 5  # Change if slot 5 is already in use
```

### Optional Customization

**Change sync frequency** (default: every hour):
```yaml
scan_interval: 3600  # Seconds (3600 = 1 hour)
```

**Adjust booking look-ahead window** (default: 60 days):
```yaml
to: "{{ (now() + timedelta(days=60)).strftime('%Y-%m-%d') }}"
```

**Modify reminder times**:
- Check-in reminder: Line ~272 (default: 9:00 AM)
- Check-out reminder: Line ~295 (default: 8:00 AM)

## Lock-Specific Configuration

### Z-Wave Locks (Z-Wave JS)

Use the default configuration:
```yaml
service: lock.set_usercode
service: lock.clear_usercode
```

### Zigbee Locks (ZHA)

Replace service calls with:
```yaml
service: zha.set_lock_user_code
data:
  code_slot: 5
  user_code: "{{ states('input_text.current_lock_code') }}"
```

### Schlage Encode (Wi-Fi)

Check if your integration supports `lock.set_usercode`. If not, you may need a custom integration or webhook.

### August Locks

August locks typically use the August integration's specific services. Consult the [August integration docs](https://www.home-assistant.io/integrations/august/).

## Dashboard Card

Add this to your Lovelace dashboard for easy monitoring:

```yaml
type: vertical-stack
cards:
  - type: markdown
    content: |
      ## 🏠 OwnerRez Guest Management
      **Current Guest:** {{ states('input_text.current_guest_name') }}
      **Lock Code Active:** {{ states('input_boolean.lock_code_active') }}
  - type: entities
    entities:
      - entity: input_text.current_guest_name
        name: Guest Name
      - entity: input_text.current_lock_code
        name: Lock Code
      - entity: input_datetime.current_checkin
        name: Check-in
      - entity: input_datetime.current_checkout
        name: Check-out
      - entity: input_boolean.lock_code_active
        name: Code Active
      - type: divider
      - entity: lock.front_door
        name: Front Door Lock
      - entity: sensor.ownerrez_next_booking
        name: Next Booking ID
```

## Usage

Once installed and configured, the system works automatically:

1. **Hourly Sync**: Home Assistant checks OwnerRez for upcoming bookings
2. **Pre-Check-in**: When a new booking is found, a random 4-digit code is generated
3. **24-Hour Reminder**: You receive a notification the day before check-in
4. **Check-in**: Lock code is automatically enabled at the scheduled time
5. **Guest Arrival**: You're notified when the guest unlocks the door
6. **Check-out Reminder**: Morning notification on check-out day
7. **Check-out**: Lock code is automatically disabled and cleared

## Troubleshooting

### "Unable to connect to OwnerRez API"

- Verify your credentials in `secrets.yaml`
- Check that your Personal Access Token is still valid
- Ensure your OwnerRez account has API access enabled

### Lock code not setting

- Verify your lock entity ID is correct
- Check that the code slot number is available (not used by another code)
- Review Home Assistant logs: **Settings** → **System** → **Logs**
- Test manually: Developer Tools → Services → `lock.set_usercode`

### Notifications not working

- Verify your notification service is configured correctly
- Test notifications: Developer Tools → Services → `notify.mobile_app`
- Check notification service name matches your setup

### Bookings not syncing

- Check the REST sensor state: Developer Tools → States → `sensor.ownerrez_next_booking`
- Verify the date range in the API call includes your booking
- Check OwnerRez booking status is "confirmed"

### Time zone issues

Ensure Home Assistant's timezone matches your property's timezone:
```yaml
homeassistant:
  time_zone: "America/New_York"  # Change to your timezone
```

## Advanced Features

### Multiple Properties

To manage multiple properties, duplicate the configuration with different:
- Sensor names (`sensor.ownerrez_property1_booking`)
- Input helper names (`input_text.property1_guest_name`)
- Lock entities (`lock.property1_front_door`)
- Code slots (use different slots: 5, 6, 7, etc.)

### Email Codes to Guests

To automatically email lock codes to guests, add SMTP configuration and modify the check-in automation:

```yaml
# Add to configuration.yaml
notify:
  - name: email
    platform: smtp
    server: smtp.gmail.com
    port: 587
    sender: your-email@gmail.com
    username: !secret smtp_username
    password: !secret smtp_password
    recipient: guest@example.com

# Then use in automation:
- service: notify.email
  data:
    title: "Your Check-in Information"
    message: "Your door code is {{ states('input_text.current_lock_code') }}"
```

### Access Logs

Add a history card to track all lock events:

```yaml
type: history-graph
entities:
  - entity: lock.front_door
  - entity: input_boolean.lock_code_active
hours_to_show: 168
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/ownerrez-lock-manager/issues)
- **Home Assistant Community**: [Community Forum Thread](https://community.home-assistant.io)
- **OwnerRez API Docs**: [OwnerRez API Documentation](https://www.ownerrez.com/support/articles/api-overview)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to the Home Assistant community for inspiration and support
- Built for vacation rental hosts using OwnerRez property management

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by OwnerRez. Use at your own risk. Always test thoroughly before relying on automated lock codes for guest access.

---

⭐ If this project helps you, please consider giving it a star on GitHub!
