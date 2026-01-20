import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from wdnas_client import client as nas_client

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up My Cloud from a config entry."""
    host = entry.data["Host"]
    username = entry.data["Username"]
    password = entry.data["Password"]
    version = entry.data["Version"]

    update_interval_seconds = int(entry.options.get("update_interval", 600))
    scan_interval = timedelta(seconds=update_interval_seconds)

    client = nas_client(username, password, host, version)

    # Establish initial session
    try:
        await client.__aenter__()
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Unable to connect/authenticate to device: {err}"
        ) from err

    async def _fetch_data_from_api() -> dict[str, Any]:
        """Fetch all datapoints from the API."""
        return {
            "system_info": await client.system_info(),
            "system_status": await client.system_status(),
            "device_info": await client.device_info(),
            "system_version": await client.system_version(),
        }

    async def async_update_data() -> dict[str, Any]:
        """Fetch data; re-authenticate if session expires."""
        try:
            data = await _fetch_data_from_api()
        except Exception as err:
            # wdnas-client doesn't expose a stable exception type here, so fallback to string check
            if "403" in str(err):
                _LOGGER.warning("Session expired (403). Re-authenticating and retrying.")
                try:
                    await client.__aenter__()
                    data = await _fetch_data_from_api()
                except Exception as retry_err:
                    raise UpdateFailed(f"Re-authentication failed: {retry_err}") from retry_err
            else:
                raise UpdateFailed(f"Error fetching data: {err}") from err

        if not isinstance(data, dict):
            raise UpdateFailed("Unexpected empty/invalid response from device")

        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_method=async_update_data,
        update_interval=scan_interval,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # Ensure we have initial data BEFORE setting up platforms
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        # Cleanup on failure
        try:
            await client.__aexit__(type(err), err, err.__traceback__)
        except Exception:
            pass
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise ConfigEntryNotReady(f"Initial fetch failed: {err}") from err

    # Reload entry on options change (e.g., update_interval)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    entry_data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if entry_data:
        client = entry_data.get("client")
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except Exception as err:
                _LOGGER.debug("Error while closing client: %s", err)

    return unload_ok

