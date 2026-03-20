import logging
import os
import json
import shutil

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import timedelta
from homeassistant.util import Throttle
from pathlib import Path
from .const import DOMAIN, OUTBOX, SENT, INBOX, DELETE
from .notify import RaspiSMSNotificationService

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=1)

async def async_setup_entry( hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:

    data = hass.data[DOMAIN][entry.entry_id]
    
    generic_outbox = GenericFolderSensor(entry, data, "outbox", "OutBox", OUTBOX)
    hass.data[DOMAIN][entry.entry_id]["generic_outbox"] = generic_outbox
    
    generic_sent = GenericFolderSensor(entry, data, "sent", "Sent", SENT)
    hass.data[DOMAIN][entry.entry_id]["generic_sent"] = generic_sent
    
    generic_inbox = GenericFolderSensor(entry, data, "inbox", "Inbox", INBOX)
    hass.data[DOMAIN][entry.entry_id]["generic_inbox"] = generic_inbox
    
    generic_delete = GenericFolderSensor(entry, data, "delete", "Delete", DELETE)
    hass.data[DOMAIN][entry.entry_id]["generic_delete"] = generic_delete
    
    sensors = [
        GenericTypeSensor(entry, data),
        generic_outbox,
        generic_sent,
        generic_inbox,
        generic_delete,
        GenericCountSensor(entry, data),
    ]
    
    if entry.data.get("select_mode", "Unknown") == "RaspiSMS":  
    
        sensors = sensors + [
            RaspiSMSHostSensor(entry, data),
        ]
    
    async_add_entities(sensors, update_before_add=True)


class GenericTypeSensor(SensorEntity):
    
    def __init__(self, entry: ConfigEntry, data: str):
        self._entry_id = entry.entry_id
        self._attr_name = f"{entry.data.get('select_mode')} ({entry.data.get('host')}) Type"
        self._attr_unique_id = f"{entry.data.get('select_mode')}_{entry.data.get('host')}_type"
        self._attr_native_value = entry.data.get("select_mode", "Unknown")
        self._attr_icon = "mdi:chip"
                
    @property
    def should_poll(self) -> bool:
        return True
        
    async def async_update(self):
            
        storage_dir = self.hass.config.path(".storage", DOMAIN, OUTBOX)
        if os.path.exists(storage_dir):
        
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
                        
            if entry:            
                service = RaspiSMSNotificationService(entry.data)
                
                entry_data = self.hass.data[DOMAIN][self._entry_id]
                store = entry_data.get("store")
        
                count = entry_data.get("count", 0) 
                initial_count = count
                _LOGGER.error("INITIAL %s", initial_count)
                
                for file_path in Path(storage_dir).glob(f"{self._entry_id}*.json"):
                
                    if file_path.is_file():
            
                        try:
                        
                            content_raw = await self.hass.async_add_executor_job(
                                file_path.read_text, "utf-8"
                            )
            
                            if not content_raw.strip():
                                continue
                            
                            data = json.loads(content_raw)
                            
                            _LOGGER.debug("SMS %s %s %s", data.get('numbers'), data.get('message'), data.get('url',''))
                            
                            message=data.get('message')
                            date=data.get('date')
                            time=data.get('time')
                            
                            content=f"{date} à {time}\n{message}"
                            
                            await service.async_send_message(
                                message=content, 
                                numbers=data.get('numbers'), 
                                url=data.get('url')
                            )
                            
                            # Logique de déplacement au lieu de unlink
                            def move_to_sent(src_path):
                                storage_dir = self.hass.config.path(".storage", DOMAIN, SENT)
                                if not os.path.exists(storage_dir):
                                    os.makedirs(storage_dir, exist_ok=True)
                                
                                dest_path = os.path.join(storage_dir, src_path.name)
                                shutil.move(str(src_path), dest_path)

                            await self.hass.async_add_executor_job(move_to_sent, file_path)
                            _LOGGER.info("Fichier %s déplacé vers %s", file_path.name, storage_dir)
                            
                            count += 1
                            _LOGGER.error("COUNT %s", count)
                                
                        except Exception as e:
                            _LOGGER.error("Erreur lors du traitement de %s : %s", file_path.name, e)

                if count > initial_count:
                
                    self.hass.data[DOMAIN][self._entry_id]["count"] = count
                    
                    stored_data = await store.async_load() or {}
                    stored_data["count"] = count
                    await store.async_save(stored_data)
                    
                    self.hass.data[DOMAIN][self._entry_id]["count"] = count
                    _LOGGER.debug("Compteur RaspiSMS mis à jour : %s", count)
                    
                    for entity in self.hass.data[DOMAIN][self._entry_id].values():
                        if isinstance(entity, SensorEntity) and entity.enabled:
                            entity.async_write_ha_state()
            
                    _LOGGER.error("Compteur RaspiSMS sauvegardé : %s", count)
                
            else:
                _LOGGER.warning("Could not find config entry for ID %s", self._entry_id)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }
        
class GenericFolderSensor(SensorEntity):
    
    def __init__(self, entry: ConfigEntry, data: str, id: str, name: str, path: str):
        self._entry = entry
        self._id = id
        self._name = name
        self._path = path
        #self._attr_name = f"{entry.data.get('select_mode')} ({entry.data.get('host')}) {name}"
        self._attr_unique_id = f"{entry.data.get('select_mode')}_{entry.data.get('host')}_{id}"
        self._attr_native_value = 0
        self._attr_icon = "mdi:numeric"
        self.translation_key = f"raspisms_{id}" # Doit correspondre au JSON
        self._attr_has_entity_name = True

    @property
    def should_poll(self) -> bool:
        return True
        
    async def async_update(self):
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        data[self._id] = await self.hass.async_add_executor_job(self._count_files)
        _LOGGER.debug("%s %s", self._path, data[self._id])
        self._attr_native_value = data[self._id]
        #await data["store"].async_save({ self._id: data[self._id] })
        
    def _count_files(self):
        try:
            storage_dir = self.hass.config.path(".storage", DOMAIN, self._path)
            if not os.path.exists(storage_dir):
                os.makedirs(storage_dir, exist_ok=True)
                return 0
            return len([f for f in Path(storage_dir).glob(f"{self._entry.entry_id}*.json") if f.is_file()])
        except Exception as e:
            _LOGGER.error("Erreur lors du comptage des fichiers dans %s: %s", storage_dir, e)
            return self._attr_native_value

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }
            
class GenericCountSensor(SensorEntity):
    
    def __init__(self, entry: ConfigEntry, data: str):
        self._entry = entry
        self._entry_id = entry.entry_id
        #self._attr_name = f"{entry.data.get('select_mode')} ({entry.data.get('host')}) Count"
        self._attr_unique_id = f"{entry.data.get('select_mode')}_{entry.data.get('host')}_count"
        self._attr_native_value = 0
        self._attr_icon = "mdi:numeric"
        self.translation_key = "raspisms_count" # Doit correspondre au JSON
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        return self.hass.data[DOMAIN][self._entry_id].get("count", 0)
        
    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }

class RaspiSMSHostSensor(SensorEntity):
    
    def __init__(self, entry: ConfigEntry, data: str):
        self._entry = entry
        #self._attr_name = f"{entry.data.get('select_mode')} ({entry.data.get('host')}) Host"
        self._attr_unique_id = f"{entry.data.get('select_mode')}_{entry.data.get('host')}_host"
        self._attr_native_value = entry.data.get("host")
        self._attr_icon = "mdi:server"
        self.translation_key = "raspisms_host" # Doit correspondre au JSON
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }
