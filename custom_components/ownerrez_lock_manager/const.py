"""Constants for OwnerRez Lock Manager."""

DOMAIN = "ownerrez_lock_manager"

# ── Config entry keys ─────────────────────────────────────────────────────────
CONF_USERNAME = "username"
CONF_TOKEN = "token"
CONF_PROPERTY_ID = "property_id"
CONF_LOCK_ENTITIES = "lock_entities"
CONF_CODE_SLOTS = "code_slots"
CONF_PRIMARY_LOCK = "primary_lock"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_LOOKAHEAD_DAYS = "lookahead_days"
CONF_LOOKBACK_DAYS = "lookback_days"
CONF_CHECKIN_BUFFER_MINUTES = "checkin_buffer_minutes"
CONF_LOCK_SERVICE_TYPE = "lock_service_type"

# ── API ───────────────────────────────────────────────────────────────────────
API_BASE = "https://api.ownerrez.com/v2"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_LOOKAHEAD = 90
DEFAULT_LOOKBACK = 7
DEFAULT_CHECKIN_BUFFER_MINUTES = 5
POLL_INTERVAL_SECONDS = 3600

# ── Lock service types ────────────────────────────────────────────────────────
LOCK_SERVICE_ZWAVE = "zwave_js"
LOCK_SERVICE_LOCK = "lock"
LOCK_SERVICE_OPTIONS = [LOCK_SERVICE_ZWAVE, LOCK_SERVICE_LOCK]

# ── Storage ───────────────────────────────────────────────────────────────────
STORAGE_VERSION = 1

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "2.0.3"

# ── Platforms ─────────────────────────────────────────────────────────────────
PLATFORMS = ["sensor", "binary_sensor", "button"]

# ── Services ──────────────────────────────────────────────────────────────────
SERVICE_ACTIVATE_EARLY = "activate_code_early"
SERVICE_CLEAR_CODE = "clear_guest_code"
SERVICE_REFRESH = "refresh_bookings"
