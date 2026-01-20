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
    """Set up the WD My Cloud sensor platform."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not entry_data:
        _LOGGER.error("Coordinator not found for entry_id=%s", config_entry.entry_id)
        return

    coordinator = entry_data["coordinator"]

    # Coordinator should have completed its first refresh in __init__.py, but be defensive.
    if not isinstance(getattr(coordinator, "data", None), dict):
        await coordinator.async_request_refresh()

    data = coordinator.data or {}
    device_info_data = data.get("device_info")
    system_version_data = data.get("system_version")

    if not isinstance(device_info_data, dict) or not isinstance(system_version_data, dict):
        _LOGGER.error("Missing device_info/system_version in coordinator data: %s", data)
        return

    serial_number = device_info_data.get("serial_number") or device_info_data.get("serial")
    device_name = device_info_data.get("name") or "WD My Cloud"
    if not serial_number:
        _LOGGER.error("Device serial number missing in device_info: %s", device_info_data)
        return

    device = DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=device_name,
        manufacturer="Western Digital",
        model=device_info_data.get("description") or device_info_data.get("model") or "My Cloud",
        sw_version=system_version_data.get("firmware"),
    )

    sensors_to_add = [
        MyCloudCPUSensor(
            coordinator,
            device,
            "CPU Usage",
            "cpu_usage",
            "system_info",
            "cpu",
            SensorDeviceClass.POWER_FACTOR,
            "%",
            SensorStateClass.MEASUREMENT
        ),
        MyCloudMemorySensor(
            coordinator,
            device,
            "Memory Usage",
            "memory_usage",
            "system_info",
            "memory",
            SensorDeviceClass.POWER_FACTOR,
            "%",
            SensorStateClass.MEASUREMENT
        ),
        MyCloudTemperatureSensor(
            coordinator,
            device,
            "System Temperature",
            "system_temperature",
            "system_status",
            "temperature",
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
            SensorStateClass.MEASUREMENT
        ),
        MyCloudStorageUsedSensor(
            coordinator,
            device,
            "Storage Used",
            "storage_used",
            "system_status",
            "storage_used",
            SensorDeviceClass.DATA_SIZE,
            "GB",
            SensorStateClass.TOTAL_INCREASING
        ),
        MyCloudStorageFreeSensor(
            coordinator,
            device,
            "Storage Free",
            "storage_free",
            "system_status",
            "storage_free",
            SensorDeviceClass.DATA_SIZE,
            "GB",
            SensorStateClass.MEASUREMENT
        ),
        MyCloudFanSpeedSensor(
            coordinator,
            device,
            "Fan Speed",
            "fan_speed",
            "system_status",
            "fan_speed",
            SensorDeviceClass.SPEED,
            "RPM",
            SensorStateClass.MEASUREMENT
        ),
        MyCloudUptimeSensor(
            coordinator,
            device,
            "Uptime",
            "uptime",
            "system_status",
            "uptime",
            None,
            "seconds",
            SensorStateClass.MEASUREMENT
        ),
        MyCloudFirmwareSensor(
            coordinator,
            device,
            "Firmware Version",
            "firmware_version",
            "system_version",
            "firmware",
            None,
            None,
            None
        ),
        MyCloudModelSensor(
            coordinator,
            device,
            "Model",
            "model",
            "device_info",
            "description",
            None,
            None,
            None
        ),
        MyCloudSerialSensor(
            coordinator,
            device,
            "Serial Number",
            "serial_number",
            "device_info",
            "serial_number",
            None,
            None,
            None
        ),
        MyCloudRaidStatusSensor(
            coordinator,
            device,
            "RAID Status",
            "raid_status",
            "system_status",
            "raid_status",
            None,
            None,
            None
        ),
        MyCloudDiskHealthBinarySensor(
            coordinator,
            device,
            "Disk Health",
            "disk_health",
            "system_status",
            "disk_health"
        ),
        MyCloudInternetConnectionBinarySensor(
            coordinator,
            device,
            "Internet Connection",
            "internet_connection",
            "system_status",
            "internet_connection"
        ),
        MyCloudPowerStatusBinarySensor(
            coordinator,
            device,
            "Power Status",
            "power_status",
            "system_status",
            "power_status"
        ),
    ]

    async_add_entities(sensors_to_add)


class MyCloudBaseEntity(CoordinatorEntity):
    """Base Entity for MyCloud integration."""

    def __init__(self, coordinator, device: DeviceInfo, name: str, unique_id: str):
        super().__init__(coordinator)
        self._attr_device_info = device
        self._attr_name = name
        self._attr_unique_id = unique_id


class MyCloudBaseSensor(MyCloudBaseEntity, SensorEntity):
    """Base Sensor for MyCloud integration."""

    def __init__(
        self,
        coordinator,
        device: DeviceInfo,
        name: str,
        unique_id: str,
        root_key: str,
        data_key: str,
        device_class,
        unit,
        state_class,
    ):
        super().__init__(coordinator, device, name, unique_id)
        self._root_key = root_key
        self._data_key = data_key
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        root = data.get(self._root_key, {})
        if isinstance(root, dict):
            return root.get(self._data_key)
        return None


class MyCloudCPUSensor(MyCloudBaseSensor):
    pass


class MyCloudMemorySensor(MyCloudBaseSensor):
    pass


class MyCloudTemperatureSensor(MyCloudBaseSensor):
    pass


class MyCloudStorageUsedSensor(MyCloudBaseSensor):
    pass


class MyCloudStorageFreeSensor(MyCloudBaseSensor):
    pass


class MyCloudFanSpeedSensor(MyCloudBaseSensor):
    pass


class MyCloudUptimeSensor(MyCloudBaseSensor):
    pass


class MyCloudFirmwareSensor(MyCloudBaseSensor):
    pass


class MyCloudModelSensor(MyCloudBaseSensor):
    pass


class MyCloudSerialSensor(MyCloudBaseSensor):
    pass


class MyCloudRaidStatusSensor(MyCloudBaseSensor):
    pass


class MyCloudBaseBinarySensor(MyCloudBaseEntity, BinarySensorEntity):
    """Base Binary Sensor for MyCloud integration."""

    def __init__(
        self,
        coordinator,
        device: DeviceInfo,
        name: str,
        unique_id: str,
        root_key: str,
        data_key: str,
    ):
        super().__init__(coordinator, device, name, unique_id)
        self._root_key = root_key
        self._data_key = data_key

    @property
    def is_on(self):
        data = self.coordinator.data or {}
        root = data.get(self._root_key, {})
        if isinstance(root, dict):
            return bool(root.get(self._data_key))
        return None


class MyCloudDiskHealthBinarySensor(MyCloudBaseBinarySensor):
    pass


class MyCloudInternetConnectionBinarySensor(MyCloudBaseBinarySensor):
    pass


class MyCloudPowerStatusBinarySensor(MyCloudBaseBinarySensor):
    pass

