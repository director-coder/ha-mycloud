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
        MyCloudCPUSensor(coordinator, device, serial_number, device_name),
        MyCloudMemoryUsageSensor(coordinator, device, serial_number, device_name),
        MyCloudTotalStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUsedStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUnusedStorageSensor(coordinator, device, serial_number, device_name),
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


# -----------------------
# Base entities
# -----------------------

class MyCloudBase(CoordinatorEntity):
    def __init__(self, coordinator, device: DeviceInfo, unique_id: str, name: str):
        super().__init__(coordinator)
        self._attr_device_info = device
        self._attr_unique_id = unique_id
        self._attr_name = name


# -----------------------
# Main device sensors
# -----------------------

class MyCloudCPUSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_cpu_usage", f"{device_name} CPU Usage")

    @property
    def native_value(self):
        # RAW: system_status.cpu is int (0..100)
        data = self.coordinator.data or {}
        cpu = _get_dict(data, "system_status").get("cpu")
        return cpu


class MyCloudMemoryUsageSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator, device, f"{serial_number}_memory_usage", f"{device_name} Memory Usage")

    @property
    def native_value(self):
        # RAW: system_status.memory.total/unused (KiB)
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
        if total is None:
            return None
        return round(total / (1024 ** 3), 2)


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
        if used is None:
            return None
        return round(used / (1024 ** 3), 2)


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
        if unused is None:
            return None
        return round(unused / (1024 ** 3), 2)


# -----------------------
# Disk sensors
# -----------------------

class MyCloudDiskTempSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(
            coordinator,
            device,
            f"{disk_sn}_temperature",
            f"{device_name} Disk {disk_name} Temperature",
        )
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
        super().__init__(
            coordinator,
            device,
            f"{disk_sn}_size",
            f"{device_name} Disk {disk_name} Size",
        )
        self._disk_name = disk_name

    @property
    def native_value(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        if not disk:
            return None
        size = disk.get("size")
        if size is None:
            return None
        return round(size / (1024 ** 3), 2)


class MyCloudDiskHealthyBinarySensor(MyCloudBase, BinarySensorEntity):
    # healthy itself is not "problem"; but you can keep as plain binary sensor
    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(
            coordinator,
            device,
            f"{disk_sn}_healthy",
            f"{device_name} Disk {disk_name} Healthy",
        )
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("healthy")


class MyCloudDiskSleepBinarySensor(MyCloudBase, BinarySensorEntity):
    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(
            coordinator,
            device,
            f"{disk_sn}_sleep",
            f"{device_name} Disk {disk_name} Sleeping",
        )
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        # RAW: key is "sleep" (bool)
        return None if not disk else disk.get("sleep")


class MyCloudDiskFailedBinarySensor(MyCloudBase, BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(
            coordinator,
            device,
            f"{disk_sn}_failed",
            f"{device_name} Disk {disk_name} Failed",
        )
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("failed")


class MyCloudDiskOverTempBinarySensor(MyCloudBase, BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, disk_sn, disk_name, device_name):
        super().__init__(
            coordinator,
            device,
            f"{disk_sn}_over_temp",
            f"{device_name} Disk {disk_name} Over Temperature",
        )
        self._disk_name = disk_name

    @property
    def is_on(self):
        disk = _find_disk(self.coordinator.data or {}, self._disk_name)
        return None if not disk else disk.get("over_temp")


# -----------------------
# Volume sensors
# -----------------------

class MyCloudVolumeSizeSensor(MyCloudBase, SensorEntity):
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(
            coordinator,
            device,
            f"volume_{volume_id}_size",
            f"{device_name} {volume_name} Size",
        )
        self._volume_id = volume_id

    @property
    def native_value(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        if not vol:
            return None
        size = vol.get("size")
        if size is None:
            return None
        return round(size / (1024 ** 3), 2)


class MyCloudVolumeMountedBinarySensor(MyCloudBase, BinarySensorEntity):
    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(
            coordinator,
            device,
            f"volume_{volume_id}_mounted",
            f"{device_name} {volume_name} Mounted",
        )
        self._volume_id = volume_id

    @property
    def is_on(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        return None if not vol else vol.get("mounted")


class MyCloudVolumeUnlockedBinarySensor(MyCloudBase, BinarySensorEntity):
    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(
            coordinator,
            device,
            f"volume_{volume_id}_unlocked",
            f"{device_name} {volume_name} Unlocked",
        )
        self._volume_id = volume_id

    @property
    def is_on(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        return None if not vol else vol.get("unlocked")


class MyCloudVolumeEncryptedBinarySensor(MyCloudBase, BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, volume_id: str, volume_name: str, device_name: str):
        super().__init__(
            coordinator,
            device,
            f"volume_{volume_id}_encrypted",
            f"{device_name} {volume_name} Encrypted",
        )
        self._volume_id = volume_id

    @property
    def is_on(self):
        vol = _find_volume(self.coordinator.data or {}, self._volume_id)
        return None if not vol else vol.get("encrypted")

