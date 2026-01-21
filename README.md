# <img src="images/icon.png" alt="WD My Cloud App Icon" width="100"> ha-mycloud

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=J-shw&repository=ha-mycloud&category=Integration)

Forked version based on original development from https://github.com/J-shw/ha-mycloud/
---
I did it because original one does not work for me on my device MyCloudEX2Ultra 2-Bay NAS
It raised an error for me once installed: https://github.com/J-shw/ha-mycloud/issues/47
And I decided to make it work and my ChatGPT was so helpy that we have created a more powerful product in a couple of days.

Integration now reads more extended info from NAS and creates more entities than described below. 

Also this Home Assistant solution extends the custom WD My Cloud EX2 Ultra integration with a Supervisor add-on that provides a full in-UI experience for managing NAS shares.

The add-on automatically discovers available shares from Home Assistant entities, allows mounting them as Supervisor Network Storage with one click, and supports per-share selection of usage (share, media, or backup).

Each share can have its own credentials, while public shares mount without authentication. Mount status and errors are shown directly in the interface (including clear feedback when authentication is required), without disruptive pop-ups.

The UI remains stable even if the underlying integration is offline, and all mounts are performed safely via the Supervisor API, making the shares immediately available to Home Assistant and add-ons.

Hope you enjoy such additions, a bit later I will check if that works on my second 4-Bay NAS from WD. Both I own are on version 2, so I am not sure if that works for version 5 correctly - needs to be tested. 

ha-mycloud/  Same URL in my repo goes for:
 - wd-mycloud-mount-helper/ - Addon
 - custom_components/ - Integration

---


Home Assistant integration for Western Digital My Cloud NAS devices.

This integration is powered by the [wdnas-client](https:/Python/Projects/WDNAS-Client) Python library, which handles all communication with the NAS.

---

## Features
- **System Status**: Monitor CPU and memory usage of your My Cloud device.
- **Device Information**: See key details like serial number, name, and firmware version.
- **Disk Information**: See key details about disks, including their health status.
- **Volume Information**: View all volumes size, encryption status and more.

---

## Installation

### HACS (Recommended)
1. Add this repository in HACS.
2. Search for "WD My Cloud" and install the integration.
3. Restart Home Assistant.

### Manual
1. Copy the `custom_components/mycloud` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

---

## Configuration

> [!IMPORTANT]  
> The Admin account can only be active in one place at a time (either the NAS Web UI or this integration).

1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration** and search for "**WD My Cloud**".
3.  Enter your device's **IP address** or **hostname** (e.g., `192.168.1.10` or `wdmycloud`). Do **not** include `http://` or `https://`.
4.  Enter your username and password (Must be an **admin** account)
5. Select NAS software version (Currently 2 or 5 are supported)

---

## Supported Devices & Contributing

This integration currently supports V2 and V5 firmware. You can see a list of tested models in the client library's documentation:

* **[View Known Supported Models](https://github.com/J-shw/wdnas_client/blob/dev/docs/SUPPORTED_MODELS.md)**

**Want to add your device?**

If your model isn't on the list, or if you have a different firmware version, I'd love to add support for it. Please **[open a GitHub Issue](https://github.com/J-shw/ha-mycloud/issues/new?template=new_device_request.md)** and we can work together to get it added.

---

## Example
<img alt="Screenshot of integration use in Home Assistant" src="https://github.com/user-attachments/assets/0b93e3d9-71ba-4386-93f2-75c210a65656" />

---

## Entities

This integration provides the following entities. `[disk_name]` and `[volume_name]` will be replaced by the actual names found on your device.

### Sensors
* **CPU Usage**: `sensor.wd_my_cloud_cpu_usage`
* **Memory Usage**: `sensor.wd_my_cloud_memory_usage`
* **Total Storage**: `sensor.wd_my_cloud_total_storage`
* **Used Storage**: `sensor.wd_my_cloud_used_storage`
* **Unused Storage**: `sensor.wd_my_cloud_unused_storage`
* **Disk Temperature**: `sensor.wd_my_cloud_disk_[disk_name]_temperature`
* **Disk Size**: `sensor.wd_my_cloud_disk_[disk_name]_size`
* **Volume Size**: `sensor.wd_my_cloud_volume_[volume_name]_size`

### Binary Sensors
* **Disk Healthy**: `binary_sensor.wd_my_cloud_disk_[disk_name]_healthy`
* **Disk Sleeping**: `binary_sensor.wd_my_cloud_disk_[disk_name]_sleeping`
* **Disk Failed**: `binary_sensor.wd_my_cloud_disk_[disk_name]_failed`
* **Disk Over Temperature**: `binary_sensor.wd_my_cloud_disk_[disk_name]_over_temperature`
* **Volume Mounted**: `binary_sensor.wd_my_cloud_volume_[volume_name]_mounted`
* **Volume Unlocked**: `binary_sensor.wd_my_cloud_volume_[volume_name]_unlocked`
* **Volume Encrypted**: `binary_sensor.wd_my_cloud_volume_[volume_name]_encrypted`
