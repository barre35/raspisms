import logging
import uuid
import voluptuous as vol
import json
import os
import shutil

from homeassistant.helpers import label_registry as lr
from homeassistant.helpers import entity_registry as er
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.helpers.storage import Store
from homeassistant.components import camera
from homeassistant.helpers.network import get_url

from datetime import datetime

from .const import DOMAIN, OUTBOX, WWW, TEMP, STORAGE_VERSION, STORAGE_KEY, SERVICE_SHORT_MESSAGE, PLATFORM

_LOGGER = logging.getLogger(__name__)

# =================
# Setup integration
# =================

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    
    _LOGGER.debug("Setup message integration.")
    
    # Gestion du stockage local
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
    stored_data = await store.async_load() or { }
    
    # Stockage centralisé dans hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "generic_outbox": None,
        "generic_sent": None,
        "host": entry.data.get("host"),
        "api_key": entry.data.get("api_key"),
        "select_mode": entry.data.get("select_mode"),
        "count": 0,
        "outbox": stored_data.get("outbox", 0),
        "sent": stored_data.get("sent", 0),
        "inbox": stored_data.get("inbox", 0),
        "delete": stored_data.get("delete", 0),
    }
    
    # Chargement des plateformes
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORM)
    
    # Création des services
    if not hass.services.has_service(DOMAIN, SERVICE_SHORT_MESSAGE):
    
        async def async_short_message_service(call):
        
            # ==============
            # SNAPSHOT_CAMERA
            # ===============
        
            async def snapshot_camera( camera_entity_id ):

                _LOGGER.debug("Réalisation d'un snapshot sur la caméra '%s'", camera_entity_id)
            
                image_container = await camera.async_get_image(
                    hass, camera_entity_id, timeout=15
                )
                
                image_bytes = image_container.content
            
                def save_image_to_disk():
                
                    storage_dir = hass.config.path(".storage", DOMAIN, TEMP)                    
                    os.makedirs(storage_dir, exist_ok=True)
                    full_path = os.path.join(storage_dir, f"{camera_entity_id}.jpg")
                
                    with open(full_path, "wb") as f:
                        f.write(image_bytes)
                    return full_path
            
                saved_path = await hass.async_add_executor_job(save_image_to_disk)
                
                _LOGGER.info("Snapshot sauvegardé avec succès dans %s", saved_path)
                
            # ============
            # SEND_MESSAGE
            # ============  
            
            async def send_message( number, message, url):

                _LOGGER.debug("Envoi d'un SMS '%s' vers '%s' avec l'url '%s'", message, number, url)
                
                file_name = f"{entry.entry_id}-{uuid.uuid4().hex}.json"
                now = datetime.now()
                
                payload = {
                    "numbers": str(numbers),
                    "message": str(message),
                    "date": now.strftime("%d/%m/%Y"),
                    "time": now.strftime("%H:%M:%S"),
                    "url": str(url),
                }
                
                storage_dir = hass.config.path(".storage", DOMAIN, OUTBOX)
                os.makedirs(storage_dir, exist_ok=True)
                full_path = os.path.join(storage_dir, file_name)

                def write_outbox_file():
                    try:
                        with open(full_path, 'w', encoding='utf-8') as f:
                            json.dump(payload, f, ensure_ascii=False, indent=4)
                        _LOGGER.info(f"Message sauvegardé dans {full_path}")
                    except Exception as e:
                        _LOGGER.error(f"Erreur lors de l'écriture : {e}")

                await hass.async_add_executor_job(write_outbox_file)
                
            # ============
            # ALERT CAMERA
            # ============ 
            
            async def alert_camera( number, message, camera_entity_id):

                _LOGGER.debug("Envoi d'un snapshot de la caméra '%s' vers '%s'", number)
                
                unique_id = str(uuid.uuid4().hex)
                base_url = get_url(hass, allow_internal=False)
                url = f"{base_url}/local/{unique_id}.jpg"
                
                def copy_action():
                    try:
                        storage_dir = hass.config.path(".storage", DOMAIN, TEMP)
                        source_file = os.path.join(storage_dir, f"{camera_entity_id}.jpg")
                        target_folder = hass.config.path("www")
                        target_file = os.path.join(target_folder, f"{unique_id}.jpg")
                        shutil.copy2(source_file, target_file)
                        os.chmod(target_file, 0o644)
                        return True
                    except Exception as e:
                        _LOGGER.error(f"Erreur lors de la recopie : {e}")
                        return False
                    
                await hass.async_add_executor_job(copy_action)

                file_name = f"{entry.entry_id}-{uuid.uuid4().hex}.json"
                now = datetime.now()
                
                payload = {
                    "numbers": str(numbers),
                    "message": str(message),
                    "date": now.strftime("%d/%m/%Y"),
                    "time": now.strftime("%H:%M:%S"),
                    "url": str(url),
                }
                
                storage_dir = hass.config.path(".storage", DOMAIN, OUTBOX)
                os.makedirs(storage_dir, exist_ok=True)
                full_path = os.path.join(storage_dir, file_name)

                def write_outbox_file():
                    try:
                        with open(full_path, 'w', encoding='utf-8') as f:
                            json.dump(payload, f, ensure_ascii=False, indent=4)
                        _LOGGER.info(f"Message sauvegardé dans {full_path}")
                    except Exception as e:
                        _LOGGER.error(f"Erreur lors de l'écriture : {e}")

                await hass.async_add_executor_job(write_outbox_file)
        
            # ============
            # MAIN SERVICE
            # ============
            
            command = call.data.get("title","")
            parameters = json.loads(call.data.get("message",{}))
            
            match command:
        
                case "MESSAGE":
 
                    numbers = parameters.get("numbers", [])
                    message = parameters.get("message", "")
                    url     = parameters.get("url","")
            
                    for _number in numbers:
                        _LOGGER.debug("Envoi d'un SMS '%s' vers '%s' avec l'url '%s'", message, _number, url)
                        await send_message( _number, message, url)

                case "SNAPSHOT":
            
                    numbers = parameters.get("numbers", [])
                    message = parameters.get("message", "")
                    url     = parameters.get("url","")
                    label   = parameters.get("label", None)        
                    
                    for _number in numbers:
                        _LOGGER.error("Snapshot d'un SMS '%s' vers '%s' avec l'url '%s' et label '%s'", message, _number, url, label)
                        await send_message( _number, message, url)

                    if label:                    
                        
                        label_reg = lr.async_get(hass)
                        
                        label_obj = next(
                            (l for l in label_reg.labels.values() if l.name == label), 
                            None
                        )
                        _label = label_obj.label_id if label_obj else None
                
                        if _label:
                        
                            ent_reg = er.async_get(hass)

                            entities_with_label = er.async_entries_for_label(ent_reg, _label)

                            cameras = [
                                entitiy_with_label.entity_id 
                                for entitiy_with_label in entities_with_label 
                                if entitiy_with_label.domain == "camera"
                            ]

                            for _camera in cameras:
                                _LOGGER.error(f"Snapshot '{ message } avec le label '{ label }' : '{ _camera }' sur { _number }")
                                await snapshot_camera( _camera)
                    
                case "ALERT":
            
                    numbers = parameters.get("numbers", [])
                    message = parameters.get("message", "")
                    url     = parameters.get("url","")
                    label   = parameters.get("label", None)        
                    
                    for _number in numbers:
                        _LOGGER.error("Alert d'un SMS '%s' vers '%s' avec l'url '%s' et label '%s'", message, _number, url, label)
                        await send_message( _number, message, url)

                    if label:
                                        
                        label_reg = lr.async_get(hass)
                        
                        label_obj = next(
                            (l for l in label_reg.labels.values() if l.name == label), 
                            None
                        )
                        _label = label_obj.label_id if label_obj else None
                
                        if _label:
                    
                            ent_reg = er.async_get(hass)

                            entities_with_label = er.async_entries_for_label(ent_reg, _label)

                            cameras = [
                                entitiy_with_label.entity_id 
                                for entitiy_with_label in entities_with_label 
                                if entitiy_with_label.domain == "camera"
                            ]

                            for _number in numbers:
                                for _camera in cameras:
                                    _LOGGER.error(f"Alerte '{ message } avec le label '{ label }' : '{ _camera }' sur { _number }")
                                    await alert_camera( _number, message, _camera)
                                
                case _:
                
                    _LOGGER.error(f"Command inconnue : {command}")
                            
        hass.services.async_register(
            "notify", 
            SERVICE_SHORT_MESSAGE,
            async_short_message_service, 
            schema=vol.Schema({
                vol.Required("title"): vol.All(vol.Coerce(str), cv.string),
                vol.Required("message"): vol.All(vol.Coerce(str), cv.string),
            })
        )
      
        async_set_service_schema(
            hass=hass, 
            domain="notify", 
            service=SERVICE_SHORT_MESSAGE,
            schema={
                "name": f"Notifier via l'intégration Message",
                "description": f"Notifier via l'intégration Message",
                "fields": {
                    "title": {
                        "description": "Commande : MESSAGE, SNAPSHOT ou ALERT .",
                        "example": "'TEXT'",
                        "required": True,
                        "selector": {"text": { "type": "text" }},
                    },
                    "message": {
                        "description": "Paramètre de la commande au format JSON.",
                        "example": "'{ numbers : [ +33xxxxxxxxx ], message: Alarme activée, url: https://www.hacs.xyz }",
                        "required": True,
                        "selector": {"text": {"multiline": True}},
                    },                
                },
            }
        )
                  
        return True
    
# ==================
# Unload integration
# ==================

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:

    _LOGGER.debug("Unload message integration.")
    
    # Déchargement des plateformes
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORM)
    
    if unload_ok:
    
        # Supression des services
        remaining_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state == ConfigEntryState.LOADED
        ]
        
        if not remaining_entries:
            if hass.services.has_service(DOMAIN, SERVICE_SHORT_MESSAGE):
                hass.services.async_remove(DOMAIN, SERVICE_SHORT_MESSAGE)
        
        # Netoyage du domaine
        if not hass.data[DOMAIN]:

            hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
    
