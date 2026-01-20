import logging
from datetime import timedelta
from typing import Any
import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from wdnas_client import client as nas_client

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MyCloud from a config entry (raise ConfigEntryNotReady BEFORE forwarding platforms)."""
    host = entry.data["Host"]
    username = entry.data["Username"]
    password = entry.data["Password"]
    version = entry.data["Version"]

    update_interval_seconds = int(entry.options.get("update_interval", 600))
    scan_interval = timedelta(seconds=update_interval_seconds)

    client = nas_client(username, password, host, version)

    # Open session BEFORE platform setup
    try:
        await client.__aenter__()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect/login to MyCloud: {err}") from err

    async def _safe(coro):
        try:
            return await coro
        except Exception as err:
            return {"_error": f"{type(err).__name__}: {err}"}

    async def _fetch_data_from_api() -> dict[str, Any]:
        """Fetch base data + extra endpoints for discovery (RAID/alerts/etc)."""
        data: dict[str, Any] = {
            # Base (used by sensors)
            "system_info": await client.system_info(),
            "system_status": await client.system_status(),
            "device_info": await client.device_info(),
            "system_version": await client.system_version(),

            # Extra (for testing / discovery)
            "alerts": await _safe(client.alerts()),
            "network_info": await _safe(client.network_info()),
            "share_names": await _safe(client.share_names()),
            "accounts": await _safe(client.accounts()),
        }

        # Version-specific extras (if supported by library/firmware)
        if version == 5:
            data["uptime"] = await _safe(client.uptime())
            data["usb_info"] = await _safe(client.usb_info())
            data["cloud_access"] = await _safe(client.cloud_access())
        elif version == 2:
            data["latest_version"] = await _safe(client.latest_version())

        return data

    async def _async_update_data() -> dict[str, Any]:
        try:
            data = await _fetch_data_from_api()
        except Exception as err:
            # Retry once on 403 (session expired)
            if "403" in str(err):
                _LOGGER.warning("Session expired (403). Re-authenticating and retrying.")
                try:
                    # best-effort close before re-open to avoid aiohttp session leaks
                    try:
                        await client.__aexit__(None, None, None)
                    except Exception:
                        pass

                    await client.__aenter__()
                    data = await _fetch_data_from_api()
                except Exception as retry_err:
                    raise UpdateFailed(f"Re-authentication failed: {retry_err}") from retry_err
            else:
                raise UpdateFailed(f"Error fetching data: {err}") from err

        if not isinstance(data, dict):
            raise UpdateFailed("Empty/invalid response from device")

        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_method=_async_update_data,
        update_interval=scan_interval,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # IMPORTANT: raise ConfigEntryNotReady HERE (before forwarding platforms)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        # cleanup on failure
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        try:
            await client.__aexit__(type(err), err, err.__traceback__)
        except Exception:
            pass
        raise ConfigEntryNotReady(f"Initial data fetch failed: {err}") from err

    # One-time full dump to /config for analysis
    dump_done = hass.data.setdefault(DOMAIN, {}).setdefault("_dump_done", set())
    if entry.entry_id not in dump_done:
        dump_done.add(entry.entry_id)
        path = hass.config.path(f"mycloud_full_dump_{entry.entry_id}.json")

        def _write():
            with open(path, "w", encoding="utf-8") as f:
                json.dump(coordinator.data, f, indent=2, ensure_ascii=False)

        await hass.async_add_executor_job(_write)
        _LOGGER.warning("MyCloud FULL dump written to %s", path)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

