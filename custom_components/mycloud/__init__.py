import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, HOST, USERNAME, PASSWORD, VERSION

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up My Cloud integration")

    hass.data.setdefault(DOMAIN, {})[HOST] = entry.data["Host"]
    hass.data.setdefault(DOMAIN, {})[USERNAME] = entry.data["Username"]
    hass.data.setdefault(DOMAIN, {})[PASSWORD] = entry.data["Password"]
    hass.data.setdefault(DOMAIN, {})[VERSION] = entry.data["Version"]

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)

