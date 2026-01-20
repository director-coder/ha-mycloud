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
    host = entry.data["Host"]
    username = entry.data["Username"]
    password = entry.data["Password"]
    version = entry.data["Version"]

    update_interval_seconds = int(entry.options.get("update_interval", 600))
    scan_interval = timedelta(seconds=update_interval_seconds)

    client = nas_client(username, password, host, version)

    async def _safe(coro):
        try:
            return await coro
        except Exception as err:
            return {"_error": f"{type(err).__name__}: {err}"}

    async def _fetch_data_from_api() -> dict[str, Any]:
        data: dict[str, Any] = {
            "system_info": await client.system_info(),
            "system_status": await client.system_status(),
            "device_info": await client.device_info(),
            "system_version": await client.system_version(),
            "alerts": await _safe(client.alerts()),
            "network_info": await _safe(client.network_info()),
            "share_names": await _safe(client.share_names()),
            "accounts": await _safe(client.accounts()),
        }

        if version == 5:
            data["uptime"] = await _safe(client.uptime())
            data["usb_info"] = await _safe(client.usb_info())
            data["cloud_access"] = await _safe(client.cloud_access())
        elif version == 2:
            data["latest_version"] = await _safe(client.latest_version())

        return data

    async def _try_logout():
        """Best-effort explicit logout if wdnas_client exposes it."""
        try:
            logout_fn = getattr(client, "logout", None)
            if callable(logout_fn):
                await logout_fn()
        except Exception as err:
            _LOGGER.debug("Logout failed (ignored): %s", err)

    async def _async_update_data() -> dict[str, Any]:
        try:
            await client.__aenter__()  # LOGIN
            data = await _fetch_data_from_api()
            if not isinstance(data, dict):
                raise UpdateFailed("Empty/invalid response from device")
            return data
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err
        finally:
            # try explicit logout first, then close session
            await _try_logout()
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass

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

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise ConfigEntryNotReady(f"Initial data fetch failed: {err}") from err

    # optional one-time dump
    dump_done = hass.data.setdefault(DOMAIN, {}).setdefault("_dump_done", set())
    if entry.entry_id not in dump_done:
        dump_done.add(entry.entry_id)
        path = hass.config.path(f"mycloud_full_dump_{entry.entry_id}.json")

        def _write():
            with open(path, "w", encoding="utf-8") as f:
                json.dump(coordinator.data, f, indent=2, ensure_ascii=False)

        await hass.async_add_executor_job(_write)
        _LOGGER.warning("MyCloud FULL dump written to %s", path)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok

