import logging
import os
import json
import shutil
from urllib.parse import urlparse
import aiohttp

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import BrowseMediaSource, MediaSource, MediaSourceItem, PlayMedia
from homeassistant.core import HomeAssistant
from datetime import timedelta, datetime
from homeassistant.util import Throttle
from pathlib import Path

from .const import DOMAIN

MONTHS_FR = {
    "01": "Janvier",
    "02": "Février",
    "03": "Mars",
    "04": "Avril",
    "05": "Mai",
    "06": "Juin",
    "07": "Juillet",
    "08": "Août",
    "09": "Septembre",
    "10": "Octobre",
    "11": "Novembre",
    "12": "Décembre",
}

TYPE_FR = {
    "ALERT": "Alarme",
    "BELL": "Sonnette"
}

_LOGGER = logging.getLogger(__name__)

async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """Initialise les deux sources de médias distinctes sans bloquer l'import."""
    return RaspiSMSMediaSource(hass)

class RaspiSMSMediaSource(MediaSource):
    """Définition de le source de média."""

    name = "RaspiSMS"
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialisation de la source de média avec une référence à Home Assistant."""

        super().__init__(DOMAIN)
        self.hass = hass
        self.domain = DOMAIN
        self.base_path = Path(hass.config.config_dir) / ".storage" / DOMAIN

    def _load_all_json_data_sync(self, filter: str | None) -> list[dict]:
        """Charge et fusionne les JSON de SENT et OUTBOX en une seule liste."""

        data_list = []
        seen_urls = set()
        
        # On boucle directement sur les dossiers cibles
        for box in ["SENT", "OUTBOX"]:

            folder = self.base_path / box
            
            if not folder.is_dir():
                continue

            for file_path in folder.glob("*.json"):

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = json.load(f)
                        
                        if "date" in content and "url" in content and "cmd" in content and content["cmd"] == filter:
                            
                            url = content["url"].strip()
                            
                            if url in seen_urls:
                                continue
                            
                            try:
                                dt = datetime.strptime(content["date"].strip(), "%d/%m/%Y")
                                content["_datetime"] = dt

                            except ValueError:
                                _LOGGER.warning(
                                    "Format de date invalide dans %s/%s : %s", 
                                    box, file_path.name, content["date"]
                                )
                                continue

                            content["_file_name"] = file_path.name
                            content["_box"] = box
                            seen_urls.add(url)
                            data_list.append(content)

                except (json.JSONDecodeError, OSError):
                    continue
                    
        return data_list

    async def _async_load_all_data(self, filter: str | None = None) -> list[dict]:
        """Exécute la lecture globale dans le pool de threads."""

        return await self.hass.async_add_executor_job(self._load_all_json_data_sync, filter)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Génère dynamiquement l'arborescence selon le clic utilisateur."""
        
        if item.identifier is None:

            return BrowseMediaSource(
                domain=self.domain,
                identifier="root",
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.IMAGE,
                title="RaspiSMS",
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMediaSource(
                        domain=self.domain,
                        identifier="BELL",
                        media_class=MediaClass.DIRECTORY,
                        media_content_type=MediaType.IMAGE,
                        title="Sonnette",
                        can_play=False,
                        can_expand=True,
                    ),
                    BrowseMediaSource(
                        domain=self.domain,
                        identifier="ALERT",
                        media_class=MediaClass.DIRECTORY,
                        media_content_type=MediaType.IMAGE,
                        title="Alarme",
                        can_play=False,
                        can_expand=True,
                    )
                ],
            )

        # Découpage du chemin de navigation virtuel et chargement des données complètes pour les filtrages suivants
        parts = item.identifier.split("/")
        
        # ============================
        # NIVEAU 1 : Sélection du type
        # ============================

        if len(parts) == 1 :  # ex: "ALERT" 

            node_type = parts[0]

            all_items = await self._async_load_all_data( node_type )

            years = sorted(list(set(
                x["_datetime"].strftime("%Y") for x in all_items
            )), reverse=True)
    
            return BrowseMediaSource(
                domain=self.domain,
                identifier=item.identifier,
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.IMAGE,
                title=f"RaspiSMS - {TYPE_FR.get(node_type, node_type)}",
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMediaSource(
                        domain=self.domain,
                        identifier=f"{node_type}/{yr}", 
                        media_class=MediaClass.DIRECTORY,
                        media_content_type=MediaType.IMAGE,
                        title=f"{yr}",
                        can_play=False,
                        can_expand=True,
                    ) for yr in years
                ],
            )
        
        # ============================
        # NIVEAU 2 : Sélection du mois
        # ============================

        if len(parts) == 2 :  # ex: "ALERT/2026"
            
            node_type = parts[0]
            target_year = parts[1]

            all_items = await self._async_load_all_data( node_type )

            months = sorted(list(set(
                x["_datetime"].strftime("%m") 
                for x in all_items 
                if x["_datetime"].strftime("%Y") == target_year
            )), reverse=True)

            return BrowseMediaSource(
                domain=self.domain,
                identifier=item.identifier,
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.IMAGE,
                title=f"RaspiSMS - {TYPE_FR.get(node_type, node_type)} - {target_year}",
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMediaSource(
                        domain=self.domain,
                        identifier=f"{node_type}/{target_year}/{mo}",
                        media_class=MediaClass.DIRECTORY,
                        media_content_type=MediaType.IMAGE,
                        title=f"{MONTHS_FR.get(mo, mo)} {target_year}",
                        can_play=False,
                        can_expand=True,
                    ) for mo in months
                ],
            )

        # ============================
        # NIVEAU 3 : Sélection du jour
        # ============================

        if len(parts) == 3 :  # ex: "ALERT/2026/06"

            node_type = parts[0]
            target_year = parts[1]
            target_month = parts[2]

            all_items = await self._async_load_all_data( node_type )

            days = sorted(list(set(
                x["_datetime"].strftime("%d") 
                for x in all_items 
                if x["_datetime"].strftime("%Y-%m") == f"{target_year}-{target_month}"
            )), reverse=True)

            return BrowseMediaSource(
                domain=self.domain,
                identifier=item.identifier,
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.IMAGE,
                title=f"RaspiSMS - {TYPE_FR.get(node_type, node_type)} - {MONTHS_FR.get(target_month, target_month)} {target_year}",
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMediaSource(
                        domain=self.domain,
                        identifier=f"{node_type}/{target_year}/{target_month}/{dy}",
                        media_class=MediaClass.DIRECTORY,
                        media_content_type=MediaType.IMAGE,
                        title=f"{dy} {MONTHS_FR.get(target_month, target_month)} {target_year}",         
                        can_play=False,
                        can_expand=True,
                    ) for dy in days
                ],
            )

        # ===========================
        # NIVEAU 4 : Liste des images
        # ===========================
        
        if len(parts) == 4 : # ex: "ALERT/2026/06/01"

            node_type = parts[0]    
            target_year = parts[1]
            target_month = parts[2]
            target_day = parts[3]
            
            all_items = await self._async_load_all_data( node_type )

            target_date_str = f"{target_year}-{target_month}-{target_day}"

            # Filtrage des éléments de ce jour précis
            day_items = [
                x for x in all_items 
                if x["_datetime"].strftime("%Y-%m-%d") == target_date_str
            ]

            # Tri par heure croissante basé sur le champ "time"
            day_items.sort(key=lambda x: x.get("time", "00:00:00"))

            children = []
            for item_data in day_items:
                time_label = item_data.get("time", "00:00:00")
                url_complete = item_data["url"]
                
                # Isolation du stem de l'image
                path_url = urlparse(url_complete).path
                media_id = Path(path_url).stem

                children.append(
                    BrowseMediaSource(
                        domain=self.domain,
                        identifier=media_id,
                        media_class=MediaClass.IMAGE,
                        media_content_type="image/jpeg",
                        title=time_label,
                        can_play=True,
                        can_expand=False,
                        thumbnail=path_url,
                    )
                )

            return BrowseMediaSource(
                domain=self.domain,
                identifier=item.identifier,
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.IMAGE,
                title=f"RaspiSMS - {TYPE_FR.get(node_type, node_type)} - {target_day} {MONTHS_FR.get(target_month, target_month)} {target_year}",                
                can_play=False,
                can_expand=True,
                children=children,
            )

        raise BrowseError("Élément introuvable")

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Résout l'ID pour renvoyer l'URL de l'image."""
        media_id = item.identifier
        url_finale = f"/local/{media_id}.jpg"
        return PlayMedia(url_finale, "image/jpeg")
