import voluptuous as vol
import logging

from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN
from .notify import RaspiSMSNotificationService
from awesomeversion import AwesomeVersion
from homeassistant.const import __version__ as HAVERSION

_LOGGER = logging.getLogger(__name__)
                   
# ======================================
# Options flow pour l'intégration message
# ======================================

class MessageOptionsFlow(config_entries.OptionsFlow):

    # ==============
    # Initialisation
    # ==============
    
    def __init__(self, config_entry):
        if AwesomeVersion(HAVERSION) < "2024.11.99":
            self.config_entry = config_entry
            
    # ===========
    # STEP : INIT
    # ===========
    
    async def async_step_init(self, user_input=None):    
        
        _LOGGER.debug("Mise à jour des options de l'intégration avec '%s'", user_input)
        errors = {}
        
        # =======================
        # Mise à jour des données
        # =======================

        if user_input is not None:
        
            new_data = {**self.config_entry.data, **user_input}
        
            
            self.hass.config_entries.async_update_entry(
                self.config_entry, 
                data=new_data
            )
            
            return self.async_create_entry(title="", data={})
            
        # --------------------------
        # Formulaire de modification         
        # --------------------------
        
        data = self.config_entry.data

        return self.async_show_form(
            step_id="init", 
            data_schema=vol.Schema({
                vol.Required("host", default=data.get("host", "")): str,
                vol.Required("api_key", default=data.get("api_key", "")): str,
            }),
            errors=errors
        )
        
# ======================================
# Config flow pour l'intégration message
# ======================================

class MessageConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1

    # ==============
    # Initialisation
    # ==============
    
    def __init__(self):
    
        self._data = {}
        
    # ===================
    # Option Flow handler
    # ===================
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):        
        return MessageOptionsFlow(config_entry)
        
    # ==============================================
    # Etape de saisie du choix du type d'intégration
    # ==============================================
    
    async def async_step_user(self, user_input=None):
        
        _LOGGER.debug("Mise à jour des options de l'intégration avec '%s'", user_input)
        errors = {}
        
        options_selection = {
            "RaspiSMS": "Raspi SMS",
        }
            
        # =======================
        # Mise à jour des données
        # =======================

        if user_input is not None:
        
            self._data.update(user_input)
        
            if self._data.get("select_mode") == "RaspiSMS":            
                return await self.async_step_raspi_sms_config() 
                                
            return self.async_create_entry(
                title="Ma Configuration", 
                data=user_input
            )
            
        # ====================
        # Formulaire de saisie
        # ====================
                  
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required( "select_mode", default="RaspiSMS"): vol.In(options_selection),
            }),
            errors=errors
        )
        
    # ========================================
    # Etape de saisie des options de Raspi SMS 
    # ========================================
    
    async def async_step_raspi_sms_config(self, user_input=None):    
        
        _LOGGER.debug("Mise à jour des options Raspi SMS avec '%s'", user_input)
        errors = {}
        
        # =======================
        # Mise à jour des données
        # =======================
        
        if user_input is not None:
       
            self._data.update(user_input)
            
            return await self.async_step_raspi_sms_test() 
            
        # ====================
        # Formulaire de saisie
        # ====================
        
        return self.async_show_form(
            step_id="raspi_sms_config", 
            data_schema=vol.Schema({
                vol.Required("host", default=self._data.get("host", "")): str,
                vol.Required("api_key", default=self._data.get("api_key", "")): str,
            }),
            errors=errors
        )
    
    # ======================================
    # Etape de test des options de Raspi SMS 
    # ======================================
    
    async def async_step_raspi_sms_test(self, user_input=None):
        
        _LOGGER.debug("Test des options Raspi SMS avec '%s'", user_input)
        errors = {}
        
        # =======================
        # Mise à jour des données
        # =======================
        
        if user_input is not None:
                
            test_number = user_input.get("test_number")
            
            if not test_number or len(test_number.strip()) < 5:
                
                _LOGGER.error("Invalid test number provided.")
                errors["base"] = "invalid_test_number"
                
            else:
        
                try:
                
                    service = RaspiSMSNotificationService( self._data)
                    
                    await service.async_send_message( 
                        numbers=test_number,
                        message="Test message from Home Assistant integration.",                        
                    )
                    
                    _LOGGER.debug("Test message sent successfully.")
                    
                    return self.async_create_entry(
                        title=f"{self._data.get('select_mode')} ({self._data.get('host')})",
                        data=self._data,
                    )
                    
                except Exception as e:
                    errors["base"] = "test_message_failed"
                    _LOGGER.error("Failed to send test message: %s", e)

        # ====================
        # Formulaire de saisie
        # ====================
        
        return self.async_show_form(
            step_id="raspi_sms_test", 
            data_schema=vol.Schema({
                vol.Required("test_number"): str,
            }), 
            errors=errors
        )
