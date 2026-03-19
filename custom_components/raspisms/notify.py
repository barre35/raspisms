import logging
import os
import uuid
import json
import aiohttp
from datetime import datetime
from homeassistant.components.notify import BaseNotificationService
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.config_entries import ConfigEntry

from .const import OUTBOX

_LOGGER = logging.getLogger(__name__)

ERROR_MESSAGES = {
    400: "Bad request. Please check your payload.",
    401: "Unauthorized. Verify your API key.",
    403: "Forbidden. You may not have permission to send SMS.",
    404: "Resource not found. Check the API endpoint.",
    429: "Rate limit exceeded. Please try again later.",
    500: "Internal server error. Try again later.",
    "default": "An unknown error occurred. Please check the logs.",
}

async def async_get_service(hass: HomeAssistant, config: ConfigType, discovery_info: DiscoveryInfoType = None):

    return RaspiSMSNotificationService(hass, config)

class RaspiSMSNotificationService(BaseNotificationService):

    def __init__(self, config):
        self.config = config

    async def async_send_message(self, message="", **kwargs):

        numbers = kwargs.get("numbers")
        url = kwargs.get("url", "")
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Api-Key": f"{ self.config.get('api_key') }",
        }
        
        payload = {
            "numbers": f"{ numbers }",
            "text": f"{ message }\n{ url }" if url else f"{ message }",
            "flash": "TRUE"
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            try:
                raspiurl = f"http://{ self.config.get('host') }/raspisms/api/scheduled/"
                async with session.post(raspiurl, data=payload, headers=headers) as response:
                    response_text = await response.text()

                    if response.status != 201:
                        error_message = ERROR_MESSAGES.get(
                            response.status, ERROR_MESSAGES["default"]
                        )
                        _LOGGER.error(
                            "Failed to send SMS. Status: %s, Response: %s, Error: %s",
                            response.status,
                            response_text,
                            error_message,
                        )
                        raise HomeAssistantError(f"Error: {error_message} (Response: {response_text})")

                    _LOGGER.info("SMS successfully sent to: %s", numbers)

            except aiohttp.ClientError as e:
                _LOGGER.error("ClientError while sending SMS: %s", e)
                raise HomeAssistantError(f"ClientError while sending SMS: {e}")

            except Exception as e:
                _LOGGER.error("Unexpected error while sending SMS: %s", e)
                raise HomeAssistantError(f"Unexpected error while sending SMS: {e}")

