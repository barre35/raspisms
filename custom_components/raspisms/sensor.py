import logging
import os
import json
import shutil

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import timedelta, datetime
from homeassistant.util import Throttle
from pathlib import Path
from .const import DOMAIN, OUTBOX, SENT, INBOX, DELETE
from .notify import RaspiSMSNotificationService

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=1)
PURGE_INTERVAL = timedelta(days=1)

async def async_setup_entry( hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the sensor platform for the RaspiSMS integration."""

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
    """Sensor to display the type of the RaspiSMS integration (e.g., RaspiSMS, etc.)"""
    
    def __init__(self, entry: ConfigEntry, data: str):
        """Initialize the sensor with the configuration entry and data."""

        self._entry_id = entry.entry_id
        self._attr_name = f"{entry.data.get('select_mode')} ({entry.data.get('host')}) Type"
        self._attr_unique_id = f"{entry.data.get('select_mode')}_{entry.data.get('host')}_type"
        self._attr_native_value = entry.data.get("select_mode", "Unknown")
        self._attr_icon = "mdi:chip"
        self._last_purge_date = None
        
    @property
    def should_poll(self) -> bool:
        """Indique que ce capteur doit être mis à jour périodiquement."""

        return True

    def _purge_old_sent_files_sync(self) -> None:
        """Méthode synchrone pour supprimer définitivement les JSON expirés et leurs images associées."""
        from datetime import datetime
        import json
        from pathlib import Path
        from urllib.parse import urlparse

        sent_dir = self.hass.config.path(".storage", DOMAIN, SENT)
        # Le dossier www est le dossier physique correspondant à l'URL /local/
        www_dir = Path(self.hass.config.config_dir) / "www"

        if not os.path.exists(sent_dir):
            return

        now = datetime.now()
        purged_count = 0

        # On cible uniquement les JSON correspondants à l'instance courante
        for file_path in Path(sent_dir).glob(f"{self._entry_id}*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                
                if "date" in content:
                    file_date_str = content["date"].strip()
                    try:
                        file_date = datetime.strptime(file_date_str, "%d/%m/%Y")
                        age = now - file_date
                        
                        if age.days > 365:
                            # 1. 📍 Extraction et suppression du fichier image associé si présent
                            if "cmd" in content and content["cmd"] in ["BELL", "ALERT"] and "url" in content and content["url"]:
                                try:
                                    url_path = urlparse(content["url"]).path
                                    image_name = Path(url_path).name  # Récupère "355f498b028345fb8a15fcd06cb70479.jpg"
                                    image_file_path = www_dir / image_name

                                    if image_file_path.is_file():
                                        image_file_path.unlink()
                                        _LOGGER.info("Purge : Image associée %s supprimée", image_name)
                                except Exception as img_err:
                                    _LOGGER.error(
                                        "Purge : Impossible de supprimer l'image pour %s : %s", 
                                        file_path.name, 
                                        img_err
                                    )

                            # 2. 📍 Suppression définitive du fichier JSON
                            file_path.unlink()
                            purged_count += 1
                            _LOGGER.info("Purge : Fichier index %s supprimé définitivement", file_path.name)
                            
                    except ValueError:
                        _LOGGER.warning("Purge : Format de date invalide dans %s : %s", file_path.name, file_date_str)
            except (json.JSONDecodeError, OSError) as e:
                _LOGGER.error("Purge : Impossible de traiter le fichier %s : %s", file_path.name, e)

        if purged_count > 0:
            _LOGGER.info("Purge terminée : %d messages et images associés ont été nettoyés", purged_count)

    async def async_update(self):
        """Vérifie les dossiers et traite les fichiers dans le dossier outbox."""
            
        now = datetime.now()

        if self._last_purge_date is None or (now - self._last_purge_date) >= PURGE_INTERVAL:
            _LOGGER.debug("Lancement de la purge automatique des fichiers de plus de 60 jours...")
            await self.hass.async_add_executor_job(self._purge_old_sent_files_sync)
            self._last_purge_date = now

        storage_dir = self.hass.config.path(".storage", DOMAIN, OUTBOX)
        if os.path.exists(storage_dir):
        
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
                        
            if entry:            
                service = RaspiSMSNotificationService(entry.data)
                
                entry_data = self.hass.data[DOMAIN][self._entry_id]
                store = entry_data.get("store")
        
                count = entry_data.get("count", 0) 
                initial_count = count
                _LOGGER.debug("INITIAL %s", initial_count)
                
                def get_files():
                    return list(Path(storage_dir).glob(f"{self._entry_id}*.json"))
    
                file_paths = await self.hass.async_add_executor_job(get_files)
                
                for file_path in file_paths:
                
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
                            _LOGGER.debug("COUNT %s", count)
                                
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
            
                    _LOGGER.debug("Compteur RaspiSMS sauvegardé : %s", count)
                
            else:
                _LOGGER.warning("Could not find config entry for ID %s", self._entry_id)

    @property
    def device_info(self):
        """Fournit les informations sur l'appareil pour ce capteur."""
        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }
        
class GenericFolderSensor(SensorEntity):
    """"Sensor to count the number of files in a specific folder (e.g., outbox, sent, inbox, delete)"""

    def __init__(self, entry: ConfigEntry, data: str, id: str, name: str, path: str):
        """Initialize the sensor with the configuration entry, data, and folder information."""
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
        """Indique que ce capteur doit être mis à jour périodiquement."""
        return True
        
    async def async_update(self):
        """Met à jour le nombre de fichiers dans le dossier spécifié."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        data[self._id] = await self.hass.async_add_executor_job(self._count_files)
        _LOGGER.debug("%s %s", self._path, data[self._id])
        self._attr_native_value = data[self._id]
        #await data["store"].async_save({ self._id: data[self._id] })
        
    def _count_files(self):
        """Compte le nombre de fichiers dans le dossier spécifié."""
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
        """Fournit les informations sur l'appareil pour ce capteur."""
        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }
            
class GenericCountSensor(SensorEntity):
    """Sensor to display the total count of processed messages"""

    def __init__(self, entry: ConfigEntry, data: str):
        """Initialize the sensor with the configuration entry and data."""

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
        """Retourne la valeur native du capteur, qui est le nombre total de messages traités."""

        return self.hass.data[DOMAIN][self._entry_id].get("count", 0)
        
    @property
    def device_info(self):
        """Fournit les informations sur l'appareil pour ce capteur."""

        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }

class RaspiSMSHostSensor(SensorEntity):
    """Sensor to display the host of the RaspiSMS integration"""

    def __init__(self, entry: ConfigEntry, data: str):
        """Initialize the sensor with the configuration entry and data."""

        self._entry = entry
        #self._attr_name = f"{entry.data.get('select_mode')} ({entry.data.get('host')}) Host"
        self._attr_unique_id = f"{entry.data.get('select_mode')}_{entry.data.get('host')}_host"
        self._attr_native_value = entry.data.get("host")
        self._attr_icon = "mdi:server"
        self.translation_key = "raspisms_host" # Doit correspondre au JSON
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        """Fournit les informations sur l'appareil pour ce capteur."""
        
        return {
            "identifiers": {(DOMAIN, self.platform.config_entry.entry_id)},
            "name": f"{self.platform.config_entry.data.get('select_mode')} ({self.platform.config_entry.data.get('host')})",
            "manufacturer": "@barre35",
        }
