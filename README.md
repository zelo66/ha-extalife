<div style="display: flex; align-items: center;">
  <img width="150" alt="home-assistant-word-mark-vertical-color-on-light" src="https://github.com/dgtal1/extalife_custom_component/assets/27864579/491d9e84-822f-4947-bf9e-805f16900401">
  <a href="https://www.forumextalife.pl/" style="margin-left: 10px;">
    <img src="https://yt3.ggpht.com/ytc/AKedOLRdji2oMcII8lorhHubp4V0mptIxdYMYJf25crN=s176-c-k-c0x00ffffff-no-rj" alt="ExtaLife Logo" width="200"/>
  </a>
</div>
<p></p>

ZAMEL Exta Life integration with Home Assistant based on custom component.
### Supported devices
* Switches: ROP-21, ROP-22, ROM-24
* Dimmers: RDP-21
* LED controllers: SLR-21, SLR-22
* Smart sockets: ROG-21
* Roller blind controllers: SRP-22, SRM-22
* Gate controller: ROB-21
* Heating controller: RGT-01
* Transmitters (remotes, wall switches) as event entities and device triggers: P-457/2, P-457/4, P-457/8, P-457/36, RNK-22, RNK-24, RNP-21, RNP-22, RNM-24
* Sensors: 
  * Temperature sensors: RCT-21, RCT-22, RNK-21&RNK-22 built-in
  * Flood sensor: RCZ-21
  * Motion sensor: RCR-21
  * Window sensor: RCK-21
  * Multi-sensor: RCM-21 (temp, humidity, presure and illuminance)
  * 3-phase energy meter: MEM-21
  * Wind speed meter: RCW-21

### Exta Free supported devices (via EFC-01 controller):
* Switches: ROP-01, ROP-02, ROP-05, ROP-06, ROP-07, ROM-01, ROM-10
* Dimmers: RDP-01, RDP-02, RDP-11
* Smart sockets: RWG-01
* Roller blind controllers: SRP-02, SRP-03, ROB-01

Not supported yet: GKN-01, ROP-27, LEDIX P260, Bulik DRS-985 and other devices unknown to the integration.
When the controller reports such devices, the integration shows an issue in **Settings → Repairs**. If you want
a device to be supported, open an issue and attach a traffic recording made while using the device (see below).

**Note:** Certain switches are mapped into Home Assistant light entities depending on icon assigned to them. This is to support voice control by Google Assistant and others and because switches are mostly used for light control.
### Installation

#### HACS (recommended)
1. Open HACS in Home Assistant.
2. Open the menu (three dots in the top right corner) and choose **Custom repositories**.
3. Add `https://github.com/gadulowaty/ha-extalife` with category **Integration**.
4. Search for **Exta Life** in HACS, download it and restart Home Assistant.

#### Manual
Copy the `custom_components/extalife` directory into the `custom_components` directory of your Home Assistant `config` directory and restart Home Assistant.

Minimum supported Home Assistant version: **2025.1** (tested with 2025.1 and 2026.10).

### Setup
The integration is set up from Home Assistant GUI (Settings → Devices & services → Add integration). Search for "Exta Life" on the list of possible integrations. If it's not visible - clear your browser cache and refresh page.
The integration supports Integration Options (poll intervals, switches mapped as lights, inverted cover control, disabling entities of not responding devices) - use **Configure** on the Exta Life integration card.

### Features
* **Events** - every transmitter button is an `event` entity (pressed, released, single / double / triple click,
  long press), scenes activated on the controller are reported by the `Scene` event entity of the controller.
  The same actions are available as device triggers in automations.
* **Controller diagnostics** - `Connection` and `IP address` entities of the EFC-01 device, firmware updates of the
  controller and modules via `update` entities.
* **Repairs** - an issue is raised when the controller is offline for more than 15 minutes and when the controller
  reports unsupported devices.
* **Services** - `extalife.refresh_state`, `extalife.restart`, `extalife.config_backup` and
  `extalife.record_traffic` (all but the first one for administrators only).
* **Diagnostics** - downloadable diagnostics with controller configuration; login and password are removed.
* **Traffic recording** - `extalife.record_traffic` records all messages exchanged with the controller for given
  number of minutes to `config/extalife/recordings/` (login and password removed). Such recordings are replayed by
  the tests, so attaching one to an issue is the best way to get a problem fixed or a new device supported -
  see [tests/recordings](tests/recordings/README.md).

Devices are named after their model (e.g. `ROP-21`), entities after the channel name set in the Exta Life app,
so entity ids look like `switch.rop_21_kitchen`. Renaming the device in Home Assistant lets you rename entity ids too.

### Development
Tests run against a fake EFC-01 controller (no hardware needed):
```
pip install -r requirements_test.txt
python -m pytest
ruff check custom_components tests
```
Releases: set `version` in `custom_components/extalife/manifest.json` and push a tag with the same version
(e.g. `2.3b1`) - the release workflow creates the GitHub release which HACS offers as an update.

Discussion, news and many more on https://www.forumextalife.pl/

<a href="https://buycoffee.to/dgtal1" target="_blank"><img src="https://buycoffee.to/btn/buycoffeeto-btn-primary.svg" style="width: 159px" alt="But me a coffee with buycoffee.to"></a>
