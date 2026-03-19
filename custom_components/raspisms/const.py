from homeassistant.const import Platform

DOMAIN = "raspisms"

PLATFORM: list[Platform] = [
    Platform.SENSOR
]

STORAGE_VERSION = 1

STORAGE_KEY = f"{DOMAIN}_storage"

SERVICE_SHORT_MESSAGE = "short_message"

OUTBOX = "OUTBOX"
SENT = "SENT"
INBOX = "INBOX"
DELETE= "DELETE"
TEMP= "TEMP"

WWW= "/config/www"

