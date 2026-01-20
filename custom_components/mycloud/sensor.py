import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    """Set up MyCloud sensors from a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not entry_data:
        _LOGGER.error("Missing entry data for entry_id=%s", config_entry.entry_id)
        return

    coordinator = entry_data.get("coordinator")
    if coordinator is None or not isinstance(getattr(coordinator, "data", None), dict):
        _LOGGER.error("Coordinator not ready for entry_id=%s", config_entry.entry_id)
        return

    device_info_data = coordinator.data.get("device_info") or {}
    system_version_data = coordinator.data.get("system_version") or {}

    serial_number = device_info_data.get("serial_number")
    device_name = device_info_data.get("name")
    if not serial_number or not device_name:
        _LOGGER.error("device_info missing serial_number/name: %s", device_info_data)
        return

    device = DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=device_name,
        manufacturer="Western Digital",
        model=device_info_data.get("description"),
        sw_version=system_version_data.get("firmware"),
    )

    sensors_to_add = [
        MyCloudCPUSensor(coordinator, device, serial_number, device_name),
        MyCloudMemorySensor(coordinator, device, serial_number, device_name),
        MyCloudTotalStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUsedStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUnusedStorageSensor(coordinator, device, serial_number, device_name),
    ]

    system_info = coordinator.data.get("system_info") or {}
    disks = system_info.get("disks") or []
    if isinstance(disks, list):
        for disk in disks:
            disk_serial = disk.get("sn")
            if not disk_serial:
                continue

            disk_name = f"{device_name} Disk {disk.get('name', '')}".strip()
            disk_model = disk.get("model")

            disk_device = DeviceInfo(
                identifiers={(DOMAIN, disk_serial)},
                name=disk_name,
                manufacturer="Western Digital",
                model=disk_model,
                sw_version=system_version_data.get("firmware"),
                hw_version=disk.get("rev"),
                via_device=(DOMAIN, serial_number),
            )

            sensors_to_add.extend(
                [
                    MyCloudDiskTempSensor(coordinator, disk_device, disk_serial, disk_name, disk),
                    MyCloudDiskHealthySensor(coordinator, disk_device, disk_serial, disk_name, disk),
                    MyCloudDiskSleepSensor(coordinator, disk_device, disk_serial, disk_name, disk),
                    MyCloudDiskFailedSensor(coordinator, disk_device, disk_serial, disk_name, disk),
                    MyCloudDiskOverTempSensor(coordinator, disk_device, disk_serial, disk_name, disk),
                    MyCloudDiskSizeSensor(coordinator, disk_device, disk_serial, disk_name, disk),
                ]
            )

    volumes = system_info.get("volumes") or []
    if isinstance(volumes, list):
        for volume in volumes:
            volume_id = volume.get("id")
            label = volume.get("label", "")
            if not volume_id:
                continue

            volume_name = f"{device_name} {label}".strip()

            volume_device = DeviceInfo(
                identifiers={(DOMAIN, volume_id)},
                name=volume_name,
                manufacturer="Western Digital",
                model="Storage Volume",
                via_device=(DOMAIN, serial_number),
            )

            sensors_to_add.extend(
                [
                    MyCloudVolumeSizeSensor(coordinator, volume_device, volume_name, volume),
                    MyCloudVolumeMountedSensor(coordinator, volume_device, volume_name, volume),
                    MyCloudVolumeUnlockedSensor(coordinator, volume_device, volume_name, volume),
                    MyCloudVolumeEncryptedSensor(coordinator, volume_device, volume_name, volume),
                ]
            )

    async_add_entities(sensors_to_add, True)


# =========================
# Entities (твои классы)
# =========================

class MyCloudSensorBase(CoordinatorEntity, SensorEntity):
    """Base sensor class for MyCloud."""
    def __init__(self, coordinator, device, serial_number, device_name):
        super().__init__(coordinator)
        self._device = device
        self._serial_number = serial_number
        self._device_name = device_name

    @property
    def device_info(self):
        return self._device


class MyCloudCPUSensor(MyCloudSensorBase):
    """CPU Usage sensor."""
    _attr_name = "CPU Usage"
    _attr_unique_id = "cpu_usage"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return (((data.get("system_info") or {}).get("cpu") or {}).get("usage"))


class MyCloudMemorySensor(MyCloudSensorBase):
    """Memory Usage sensor."""
    _attr_name = "Memory Usage"
    _attr_unique_id = "memory_usage"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return (((data.get("system_info") or {}).get("memory") or {}).get("usage"))


class MyCloudTotalStorageSensor(MyCloudSensorBase):
    """Total Storage sensor."""
    _attr_name = "Total Storage"
    _attr_unique_id = "total_storage"
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        total_bytes = (((data.get("system_info") or {}).get("storage") or {}).get("total"))
        if total_bytes is None:
            return None
        return round(total_bytes / (1024 ** 3), 2)


class MyCloudUsedStorageSensor(MyCloudSensorBase):
    """Used Storage sensor."""
    _attr_name = "Used Storage"
    _attr_unique_id = "used_storage"
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        used_bytes = (((data.get("system_info") or {}).get("storage") or {}).get("used"))
        if used_bytes is None:
            return None
        return round(used_bytes / (1024 ** 3), 2)


class MyCloudUnusedStorageSensor(MyCloudSensorBase):
    """Unused Storage sensor."""
    _attr_name = "Unused Storage"
    _attr_unique_id = "unused_storage"
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        free_bytes = (((data.get("system_info") or {}).get("storage") or {}).get("free"))
        if free_bytes is None:
            return None
        return round(free_bytes / (1024 ** 3), 2)


class MyCloudDiskTempSensor(MyCloudSensorBase):
    """Disk Temperature sensor."""
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator, device, disk_serial, disk_name, disk_data):
        super().__init__(coordinator, device, disk_serial, disk_name)
        self._disk_data = disk_data
        self._attr_name = f"{disk_name} Temperature"
        self._attr_unique_id = f"{disk_serial}_temperature"

    @property
    def native_value(self):
        return self._disk_data.get("temp")


class MyCloudDiskHealthySensor(MyCloudSensorBase, BinarySensorEntity):
    """Disk Healthy binary sensor."""
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, disk_serial, disk_name, disk_data):
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self._disk_data = disk_data
        self._attr_name = f"{disk_name} Healthy"
        self._attr_unique_id = f"{disk_serial}_healthy"

    @property
    def device_info(self):
        return self._device

    @property
    def is_on(self):
        return bool(self._disk_data.get("healthy"))


class MyCloudDiskSleepSensor(MyCloudSensorBase, BinarySensorEntity):
    """Disk Sleep binary sensor."""
    def __init__(self, coordinator, device, disk_serial, disk_name, disk_data):
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self._disk_data = disk_data
        self._attr_name = f"{disk_name} Sleeping"
        self._attr_unique_id = f"{disk_serial}_sleeping"

    @property
    def device_info(self):
        return self._device

    @property
    def is_on(self):
        return bool(self._disk_data.get("sleeping"))


class MyCloudDiskFailedSensor(MyCloudSensorBase, BinarySensorEntity):
    """Disk Failed binary sensor."""
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, disk_serial, disk_name, disk_data):
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self._disk_data = disk_data
        self._attr_name = f"{disk_name} Failed"
        self._attr_unique_id = f"{disk_serial}_failed"

    @property
    def device_info(self):
        return self._device

    @property
    def is_on(self):
        return bool(self._disk_data.get("failed"))


class MyCloudDiskOverTempSensor(MyCloudSensorBase, BinarySensorEntity):
    """Disk Over Temperature binary sensor."""
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, disk_serial, disk_name, disk_data):
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self._disk_data = disk_data
        self._attr_name = f"{disk_name} Over Temperature"
        self._attr_unique_id = f"{disk_serial}_over_temp"

    @property
    def device_info(self):
        return self._device

    @property
    def is_on(self):
        return bool(self._disk_data.get("over_temp"))


class MyCloudDiskSizeSensor(MyCloudSensorBase):
    """Disk Size sensor."""
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, disk_serial, disk_name, disk_data):
        super().__init__(coordinator, device, disk_serial, disk_name)
        self._disk_data = disk_data
        self._attr_name = f"{disk_name} Size"
        self._attr_unique_id = f"{disk_serial}_size"

    @property
    def native_value(self):
        size = self._disk_data.get("size")
        if size is None:
            return None
        return round(size / (1024 ** 3), 2)


class MyCloudVolumeSizeSensor(MyCloudSensorBase):
    """Volume Size sensor."""
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    def __init__(self, coordinator, device, volume_name, volume_data):
        super().__init__(coordinator, device, volume_name, volume_name)
        self._volume_data = volume_data
        self._attr_name = f"{volume_name} Size"
        self._attr_unique_id = f"{volume_name}_size"

    @property
    def native_value(self):
        size = self._volume_data.get("size")
        if size is None:
            return None
        return round(size / (1024 ** 3), 2)


class MyCloudVolumeMountedSensor(MyCloudSensorBase, BinarySensorEntity):
    """Volume Mounted binary sensor."""
    def __init__(self, coordinator, device, volume_name, volume_data):
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self._volume_data = volume_data
        self._attr_name = f"{volume_name} Mounted"
        self._attr_unique_id = f"{volume_name}_mounted"

    @property
    def device_info(self):
        return self._device

    @property
    def is_on(self):
        return bool(self._volume_data.get("mounted"))


class MyCloudVolumeUnlockedSensor(MyCloudSensorBase, BinarySensorEntity):
    """Volume Unlocked binary sensor."""
    def __init__(self, coordinator, device, volume_name, volume_data):
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self._volume_data = volume_data
        self._attr_name = f"{volume_name} Unlocked"
        self._attr_unique_id = f"{volume_name}_unlocked"

    @property
    def device_info(self):
        return self._device

    @property
    def is_on(self):
        return bool(self._volume_data.get("unlocked"))


class MyCloudVolumeEncryptedSensor(MyCloudSensorBase, BinarySensorEntity):
    """Volume Encrypted binary sensor."""
    _attr_device_class = "problem"

    def __init__(self, coordinator, device, volume_name, volume_data):
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self._volume_data = volume_data
        self._attr_name = f"{volume_name} Encrypted"
        self._attr_unique_id = f"{volume_name}_encrypted"

    @property
    def device_info(self):
        return self._device

    @property
    def is_on(self):
        return bool(self._volume_data.get("encrypted"))

