import logging
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed, CoordinatorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from wdnas_client import client as nas_client

from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    """Set up the WD My Cloud sensor platform."""
    host = config_entry.data["Host"]
    username = config_entry.data["Username"]
    password = config_entry.data["Password"]
    version = config_entry.data["Version"]

    client = nas_client(username, password, host, version)
    
    try:
        await client.__aenter__()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect/login to MyCloud: {err}") from err

    update_interval_seconds = config_entry.options.get("update_interval", 600)
    SCAN_INTERVAL = timedelta(seconds=update_interval_seconds)
    _LOGGER.debug("Update interval set to %s seconds", update_interval_seconds)


    async def _fetch_data_from_api():
        """Fetch all necessary data from the API."""
        system_info = await client.system_info()
        system_status = await client.system_status()
        device_info = await client.device_info()
        system_version = await client.system_version()

        return {
            "system_info": system_info,
            "system_status": system_status,
            "device_info": device_info,
            "system_version": system_version
        }


    async def async_update_data():
        """Fetch data from API. If session expires, attempt re-authentication and retry once."""
        try:
            return await _fetch_data_from_api()
        
        except Exception as err:
            if "403" in str(err):
                _LOGGER.warning("Session expired (403 error). Attempting to re-authenticate.")
                
                try:
                    await client.__aenter__()
                    
                    _LOGGER.debug("Re-authentication successful. Retrying data fetch.")
                    return await _fetch_data_from_api()

                except Exception as retry_err:
                    _LOGGER.error("Re-authentication failed: %s", retry_err, exc_info=True)
                    raise UpdateFailed(f"Failed to fetch data after re-authentication: {retry_err}") from retry_err
            
            _LOGGER.error("Error fetching data: %s", err, exc_info=True)
            raise UpdateFailed(f"Error fetching data: {err}") from err


    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="mycloud_coordinator",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Initial data fetch failed: {err}") from err

    if not isinstance(coordinator.data, dict):
        raise ConfigEntryNotReady("No data received from device yet")

    device_info_data = coordinator.data.get("device_info")
    system_version_data = coordinator.data.get("system_version")
    if not isinstance(device_info_data, dict) or not isinstance(system_version_data, dict):
        raise ConfigEntryNotReady("device_info/system_version missing in response")

    serial_number = device_info_data.get("serial_number")
    device_name = device_info_data.get("name")
    if not serial_number or not device_name:
        raise ConfigEntryNotReady("serial_number/name missing in device_info")

    device = DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=device_name,
        manufacturer="Western Digital",
        model=device_info_data["description"],
        sw_version=system_version_data["firmware"]
    )

    sensors_to_add = [
        MyCloudCPUSensor(coordinator, device, serial_number, device_name),
        MyCloudMemorySensor(coordinator, device, serial_number, device_name),
        MyCloudTotalStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUsedStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUnusedStorageSensor(coordinator, device, serial_number, device_name)
    ]

    system_info = coordinator.data.get("system_info") or {}
    disks = system_info.get("disks") or []
    for disk in disks:
        disk_serial = disk["sn"]
        disk_name = f"{device_name} Disk {disk['name']}"
        disk_model = disk["model"]

        disk_device = DeviceInfo(
            identifiers={(DOMAIN, disk_serial)},
            name=disk_name,
            manufacturer="Western Digital",
            model=disk_model,
            sw_version=system_version_data["firmware"],
            hw_version=disk["rev"],
            via_device=(DOMAIN, serial_number)
        )

        sensors_to_add.extend([
            MyCloudDiskTempSensor(coordinator, disk_device, disk_serial, disk_name, disk),
            MyCloudDiskHealthySensor(coordinator, disk_device, disk_serial, disk_name, disk),
            MyCloudDiskSleepSensor(coordinator, disk_device, disk_serial, disk_name, disk),
            MyCloudDiskFailedSensor(coordinator, disk_device, disk_serial, disk_name, disk),
            MyCloudDiskOverTempSensor(coordinator, disk_device, disk_serial, disk_name, disk),
            MyCloudDiskSizeSensor(coordinator, disk_device, disk_serial, disk_name, disk)
        ])

    system_info = coordinator.data.get("system_info") or {}
    volumes = system_info.get("volumes") or []
    for volume in volumes:
        volume_id = volume["id"]
        volume_name = f"{device_name} {volume['label']}"

        volume_device = DeviceInfo(
            identifiers={(DOMAIN, volume_id)},
            name=volume_name,
            manufacturer="Western Digital",
            model="Storage Volume",
            via_device=(DOMAIN, serial_number)
        )

        sensors_to_add.extend([
            MyCloudVolumeSizeSensor(coordinator, volume_device, volume_name, volume),
            MyCloudVolumeMountedSensor(coordinator, volume_device, volume_name, volume),
            MyCloudVolumeUnlockedSensor(coordinator, volume_device, volume_name, volume),
            MyCloudVolumeEncryptedSensor(coordinator, volume_device, volume_name, volume)
        ])

    async_add_entities(sensors_to_add, True)

    hass.data.setdefault(DOMAIN, {})["client_cleanup"] = client.__aexit__


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload a config entry."""
    client_cleanup = hass.data[DOMAIN].get("client_cleanup")
    if client_cleanup:
        await client_cleanup(None, None, None)
    return True


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
        return self.coordinator.data["system_info"]["cpu"]["usage"]


class MyCloudMemorySensor(MyCloudSensorBase):
    """Memory Usage sensor."""
    _attr_name = "Memory Usage"
    _attr_unique_id = "memory_usage"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

    @property
    def native_value(self):
        return self.coordinator.data["system_info"]["memory"]["usage"]


class MyCloudTotalStorageSensor(MyCloudSensorBase):
    """Total Storage sensor."""
    _attr_name = "Total Storage"
    _attr_unique_id = "total_storage"
    _attr_native_unit_of_measurement = "GB"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE

    @property
    def native_value(self):
        total_bytes = self.coordinator.data["system_info"]["storage"]["total"]
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
        used_bytes = self.coordinator.data["system_info"]["storage"]["used"]
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
        unused_bytes = self.coordinator.data["system_info"]["storage"]["free"]
        return round(unused_bytes / (1024 ** 3), 2)


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
        return self._disk_data["temp"]


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
        return self._disk_data["healthy"]


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
        return self._disk_data["sleeping"]


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
        return self._disk_data["failed"]


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
        return self._disk_data["over_temp"]


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
        return round(self._disk_data["size"] / (1024 ** 3), 2)


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
        return round(self._volume_data["size"] / (1024 ** 3), 2)


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
        return self._volume_data["mounted"]


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
        return self._volume_data["unlocked"]


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
        return self._volume_data["encrypted"]

