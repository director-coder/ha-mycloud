import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_dict(d: Any, key: str) -> dict:
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def _get_list(d: Any, key: str) -> list:
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, list) else []


def _find_disk(data: dict, disk_name: str) -> dict | None:
    sys_info = _get_dict(data, "system_info")
    for disk in _get_list(sys_info, "disks"):
        if isinstance(disk, dict) and disk.get("name") == disk_name:
            return disk
    return None


def _find_volume(data: dict, volume_id: str) -> dict | None:
    sys_info = _get_dict(data, "system_info")
    for vol in _get_list(sys_info, "volumes"):
        if isinstance(vol, dict) and str(vol.get("id")) == str(volume_id):
            return vol
    return None


def _parse_alerts(alerts_obj: Any) -> list[dict]:
    """
    Your JSON shows alerts like:
      "alerts": [ 1, [ {..}, {..} ] ]
    Sometimes it can be just list of dicts, or empty.
    Return list of alert dicts.
    """
    if alerts_obj is None:
        return []
    if isinstance(alerts_obj, list):
        # Format: [status, [alerts...]]
        if len(alerts_obj) == 2 and isinstance(alerts_obj[1], list):
            return [a for a in alerts_obj[1] if isinstance(a, dict)]
        # Format: [ {..}, {..} ]
        if all(isinstance(x, dict) for x in alerts_obj):
            return alerts_obj
    return []


def _pick_primary_iface(network_info: Any) -> tuple[str | None, dict]:
    """
    network_info is dict keyed by MAC.
    Return (mac, info_dict) for first iface.
    """
    if not isinstance(network_info, dict) or not network_info:
        return None, {}
    mac = next(iter(network_info.keys()))
    info = network_info.get(mac)
    return mac, info if isinstance(info, dict) else {}


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not entry_data:
        _LOGGER.error("Missing entry data for entry_id=%s", config_entry.entry_id)
        return

    coordinator = entry_data.get("coordinator")
    if coordinator is None or not isinstance(getattr(coordinator, "data", None), dict):
        _LOGGER.error("Coordinator not ready for entry_id=%s", config_entry.entry_id)
        return

    data = coordinator.data

    device_info_data = _get_dict(data, "device_info")
    system_version_data = _get_dict(data, "system_version")

    serial_number = device_info_data.get("serial_number")
    device_name = device_info_data.get("name") or "WD My Cloud"
    if not serial_number:
        _LOGGER.error("device_info missing serial_number: %s", device_info_data)
        return

    device = DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=device_name,
        manufacturer="Western Digital",
        model=device_info_data.get("description") or "My Cloud",
        sw_version=system_version_data.get("firmware"),
    )

    entities: list = [
        # Core
        MyCloudCPUSensor(coordinator, device, serial_number, device_name),
        MyCloudMemoryUsageSensor(coordinator, device, serial_number, device_name),
        MyCloudTotalStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUsedStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUnusedStorageSensor(coordinator, device, serial_number, device_name),

        # New: alerts/network/shares
        MyCloudAlertsCountSensor(coordinator, device, serial_number, device_name),
        MyCloudLastAlertSensor(coordinator, device, serial_number, device_name),
        MyCloudNetworkSummarySensor(coordinator, device, serial_number, device_name),
        MyCloudSharesSensor(coordinator, device, serial_number, device_name),
    ]

    # Disks
    sys_info = _get_dict(data, "system_info")
    for disk in _get_list(sys_info, "disks"):
        if not isinstance(disk, dict):
            continue
        disk_name = disk.get("name")
        disk_sn = disk.get("sn")
        if not disk_name or not disk_sn:
            continue

        disk_device = DeviceInfo(
            identifiers={(DOMAIN, disk_sn)},
            name=f"{device_name} Disk {disk_name}",
            manufacturer="Western Digital",
            model=disk.get("model"),
            sw_version=system_version_data.get("firmware"),
            hw_version=disk.get("rev"),
            via_device=(DOMAIN, serial_number),
        )

        entities.extend(
            [
                MyCloudDiskTempSensor(coordinator, disk_device, disk_sn, disk_name, device_name),
                MyCloudDiskSizeSensor(coordinator, disk_device, disk_sn, disk_name, device_name),
                MyCloudDiskHealthyBinarySensor(coordinator, disk_device, disk_sn, disk_name, device_name),
                MyCloudDiskSleepBinarySensor(coordinator, disk_device, disk_sn, disk_name, device_name),
                MyCloudDiskFailedBinarySensor(coordinator, disk_device, disk_sn, disk_name, device_name),
                MyCloudDiskOverTempBinarySensor(coordinator, disk_device, disk_sn, disk_name, device_name),
            ]
        )

    # Volumes
    for vol in _get_list(sys_info, "volumes"):
        if not isinstance(vol, dict):
            continue
        volume_id = str(vol.get("id")) if vol.get("id") is not None else None
        volume_name = vol.get("name") or vol.get("label") or f"Volume_{volume_id or '?'}"
        if not volume_id:
            continue

        volume_device = DeviceInfo(
            identifiers={(DOMAIN, f"volume_{volume_id}")},
            name=f"{device_name} {volume_name}",
            manufacturer="Western Digital",
            model="Storage Volume",
            via_device=(DOMAIN, serial_number),
        )

        entities.extend(
            [
                MyCloudVolumeSizeSensor(coordinator, volume_device, volume_id, volume_name, device_name),
                MyCloudVolumeMountedBinarySensor(coordinator, volume_device, volume_id, volume_name, device_name),
                MyCloudVolumeUnlockedBinarySensor(coordinator, volume_device, volume_id, volume_name, device_name),
                MyCloudVolumeEncryptedBinarySensor(coordinator, volume_device, volume_id, volume_name, device_name),
            ]
        )

    async_add_entities(entities, True)


class MyCloudBase(CoordinatorEntity):
    def __init__(self, coordinator, device: DeviceInfo, unique_id: str, name: str):
        super().__init__(coordinator)
        self._attr_device_info = device
        self._attr_unique_id = unique_id
        self._attr_name = name


# =========================
# Core sensors
# =========================

class MyCloudCPUSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_cpu_usage", f"{device_name} CPU Usage")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return _get_dict(data, "system_status").get("cpu")


class MyCloudMemoryUsageSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_memory_usage", f"{device_name} Memory Usage")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        mem = _get_dict(_get_dict(data, "system_status"), "memory")
        total = mem.get("total")
        unused = mem.get("unused")
        if not total or unused is None:
            return None
        used = total - unused
        return round((used / total) * 100, 1)


class MyCloudTotalStorageSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_total_storage", f"{device_name} Total Storage")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        size = _get_dict(_get_dict(data, "system_info"), "size")
        total = size.get("total")
        return None if total is None else round(total / (1024 ** 3), 2)


class MyCloudUsedStorageSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_used_storage", f"{device_name} Used Storage")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        size = _get_dict(_get_dict(data, "system_info"), "size")
        used = size.get("used")
        return None if used is None else round(used / (1024 ** 3), 2)


class MyCloudUnusedStorageSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_unused_storage", f"{device_name} Unused Storage")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        size = _get_dict(_get_dict(data, "system_info"), "size")
        unused = size.get("unused")
        return None if unused is None else round(unused / (1024 ** 3), 2)


# =========================
# New sensors: Alerts / Network / Shares
# =========================

class MyCloudAlertsCountSensor(MyCloudBase, SensorEntity):
    """Count of current alerts."""
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_alerts_count", f"{device_name} Alerts Count")

    @property
    def native_value(self):
        alerts = _parse_alerts((self.coordinator.data or {}).get("alerts"))
        return len(alerts)

    @property
    def extra_state_attributes(self):
        alerts = _parse_alerts((self.coordinator.data or {}).get("alerts"))
        # keep first 10 to avoid huge attributes
        top = alerts[:10]
        return {"alerts_preview": top}


class MyCloudLastAlertSensor(MyCloudBase, SensorEntity):
    """Last alert message (string)."""
    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_last_alert", f"{device_name} Last Alert")

    @property
    def native_value(self):
        alerts = _parse_alerts((self.coordinator.data or {}).get("alerts"))
        if not alerts:
            return None
        return alerts[-1].get("msg")

    @property
    def extra_state_attributes(self):
        alerts = _parse_alerts((self.coordinator.data or {}).get("alerts"))
        if not alerts:
            return {}
        a = alerts[-1]
        return {
            "code": a.get("code"),
            "level": a.get("level"),
            "desc": a.get("desc"),
            "time": a.get("time"),
            "seq_num": a.get("seq_num"),
        }


class MyCloudNetworkSummarySensor(MyCloudBase, SensorEntity):
    """Network summary from first interface."""
    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_network_summary", f"{device_name} Network Summary")

    @property
    def native_value(self):
        mac, info = _pick_primary_iface((self.coordinator.data or {}).get("network_info"))
        if not mac or not info:
            return None
        # show IP as state
        return info.get("ip")

    @property
    def extra_state_attributes(self):
        mac, info = _pick_primary_iface((self.coordinator.data or {}).get("network_info"))
        if not mac or not info:
            return {}
        return {
            "mac": mac,
            "ip": info.get("ip"),
            "netmask": info.get("netmask"),
            "gateway": info.get("gateway"),
            "dns1": info.get("dns1"),
            "dns2": info.get("dns2"),
            "dns3": info.get("dns3"),
            "dhcp_enable": info.get("dhcp_enable"),
            "lan_speed": info.get("lan_speed"),     # e.g. "100"
            "lan_enabled": info.get("lan_enabled"),
            "dns_manual": info.get("dns_manual"),
        }


class MyCloudSharesSensor(MyCloudBase, SensorEntity):
    """Shares summary: number of shares; list in attributes."""
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_shares_count", f"{device_name} Shares Count")

    @property
    def native_value(self):
        shares = (self.coordinator.data or {}).get("share_names")
        if not isinstance(shares, list):
            return None
        return len(shares)

    @property
    def extra_state_attributes(self):
        shares = (self.coordinator.data or {}).get("share_names")
        if not isinstance(shares, list):
            return {}
        # Put both names and paths, but keep it reasonably sized
        names = []
        items = []
        for s in shares[:50]:
            if isinstance(s, dict):
                name = s.get("share_name")
                path = s.get("path")
                if name:
                    names.append(name)
                items.append({"share_name": name, "path": path})
        return {
            "share_names": names,
            "shares": items,
        }


# =========================
# Disk sensors
# =========================

class MyCloudDiskTempSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(coordinator, device, f"{disk_sn}_temperature", f"{device_name} Disk {disk_name} Temperature")
        self._disk_name = disk_name

    @property
    def native_value(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("temp")


class MyCloudDiskSizeSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(coordinator, device, f"{disk_sn}_size", f"{device_name} Disk {disk_name} Size")
        self._disk_name = disk_name

    @property
    def native_value(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        if not disk:
            return None
        size = disk.get("size")
        return None if size is None else round(size / (1024 ** 3), 2)


class MyCloudDiskHealthyBinarySensor(MyCloudBase, BinarySensorEntity):
    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(coordinator, device, f"{disk_sn}_healthy", f"{device_name} Disk {disk_name} Healthy")
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("healthy")


class MyCloudDiskSleepBinarySensor(MyCloudBase, BinarySensorEntity):
    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(coordinator, device, f"{disk_sn}_sleep", f"{device_name} Disk {disk_name} Sleeping")
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("sleep")


class MyCloudDiskFailedBinarySensor(MyCloudBase, BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(coordinator, device, f"{disk_sn}_failed", f"{device_name} Disk {disk_name} Failed")
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("failed")


class MyCloudDiskOverTempBinarySensor(MyCloudBase, BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(coordinator, device, f"{disk_sn}_over_temp", f"{device_name} Disk {disk_name} Over Temperature")
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("over_temp")


# =========================
# Volume sensors
# =========================

class MyCloudVolumeSizeSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(coordinator, device, f"volume_{volume_id}_size", f"{device_name} {volume_name} Size")
        self._volume_id = volume_id

    @property
    def native_value(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        if not vol:
            return None
        size = vol.get("size")
        return None if size is None else round(size / (1024 ** 3), 2)


class MyCloudVolumeMountedBinarySensor(MyCloudBase, BinarySensorEntity):
    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(coordinator, device, f"volume_{volume_id}_mounted", f"{device_name} {volume_name} Mounted")
        self._volume_id = volume_id

    @property
    def is_on(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        return None if not vol else vol.get("mounted")


class MyCloudVolumeUnlockedBinarySensor(MyCloudBase, BinarySensorEntity):
    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(coordinator, device, f"volume_{volume_id}_unlocked", f"{device_name} {volume_name} Unlocked")
        self._volume_id = volume_id

    @property
    def is_on(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        return None if not vol else vol.get("unlocked")


class MyCloudVolumeEncryptedBinarySensor(MyCloudBase, BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(coordinator, device, f"volume_{volume_id}_encrypted", f"{device_name} {volume_name} Encrypted")
        self._volume_id = volume_id

    @property
    def is_on(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        return None if not vol else vol.get("encrypted")

