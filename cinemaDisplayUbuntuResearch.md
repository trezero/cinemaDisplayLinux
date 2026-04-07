# Apple LED Cinema Display 24" on Ubuntu 24 Linux — Research & Analysis

**Date:** 2026-03-26
**System Under Test:** Dell XPS 15 9520
**OS:** Ubuntu 24.04 LTS (kernel 6.8.0-106-generic)
**GPU:** Intel Iris Xe (i915) + NVIDIA GeForce RTX 3050 Mobile (driver 580-open)

---

## 1. System Hardware Inventory

### Laptop
- **Model:** Dell XPS 15 9520
- **CPU:** 12th Gen Intel Core i7-12700H
- **iGPU:** Intel Alder Lake-P GT2 (Iris Xe) — `i915` driver
- **dGPU:** NVIDIA GA107M GeForce RTX 3050 Mobile — `nvidia` driver 580-open

### USB-C / Thunderbolt Ports
- **3 USB-C ports** detected (`port0`, `port1`, `port2`)
- Thunderbolt controller: Intel Gen12
- All 3 ports are Thunderbolt 4, supporting:
  - USB 3.2 Gen 2×2 (20 Gbps)
  - DisplayPort 1.4a Alt Mode
  - USB Power Delivery

### Currently Connected USB-C Devices (at time of analysis)
- `port0-partner`: Device connected, USB PD supported, no DisplayPort alternate mode active
- `port1-partner`: Device connected, USB PD supported, **2 alternate modes detected** (both SVID `0x8087` = Intel/Thunderbolt)
- External displays: **all show "disconnected"** in `xrandr` — signal is not reaching the display pipeline yet

### Current xrandr External Outputs (all disconnected)
```
DP-1, DP-2, DP-3, DP-4 — disconnected
HDMI-1 — disconnected
```

---

## 2. Target Hardware: Apple LED Cinema Display 24" (A1267)

### Specifications
- **Resolution:** 1920×1200 (16:10)
- **Connector:** Mini DisplayPort (input)
- **USB:** Built-in 3-port USB 2.0 hub (USB-A cable connects to host)
- **Audio:** 2.1 speaker system + microphone (USB audio class device)
- **Camera:** iSight webcam (requires firmware extraction on Linux)
- **Power:** Internal 212W power supply (AC mains, IEC C13 cable)
- **MagSafe port:** Output only — charges a connected MacBook. **Not required for display operation.**
- **USB Vendor:Product ID:** `05ac:921d` (Apple, LED Cinema Display)

### Connection to Non-Mac via USB-C
The A1267 uses standard Mini DisplayPort signaling — **not** Thunderbolt. Any USB-C port with DisplayPort Alt Mode support can drive it via a passive USB-C → Mini DisplayPort adapter/cable.

**Important:** Do NOT use Apple's Thunderbolt 3 → Thunderbolt 2 adapter — despite the same physical connector shape, it uses Thunderbolt 2 signaling which is **electrically incompatible** with Mini DisplayPort.

---

## 3. Feasibility Assessment

### Overall Verdict: **YES — Fully Possible**

| Feature | Works on Linux? | Notes |
|---|---|---|
| Video output (1920×1200) | ✅ Yes | Via USB-C → Mini DP adapter + i915 driver |
| Dual display (2 monitors) | ✅ Yes | Requires 2 USB-C ports with DP Alt Mode |
| Audio (speakers + mic) | ✅ Yes | USB audio class, no driver needed |
| USB hub (3 ports) | ✅ Yes | Standard USB 2.0, no driver needed |
| Brightness control | ⚠️ Extra step | `appledisplay` kernel module or `acdcontrol` |
| iSight webcam | ⚠️ Extra step | Requires `isight-firmware-tools` package |
| MagSafe laptop charging | ❌ N/A | Mac-only, leave unplugged |
| Suspend/resume | ⚠️ Known issue | USB-C replug often required after wake |

---

## 4. Key Technical Findings

### 4.1 GPU Architecture (Critical for USB-C Display Routing)

The Dell XPS 15 9520 uses a **muxless Optimus** architecture:

> All external display outputs (Thunderbolt 4, USB-C, HDMI) are hardwired to the **Intel iGPU** — not the NVIDIA dGPU.

This is actually **favorable for Linux** because:
- The `i915` (Intel) driver is mature and reliable for display output
- No special PRIME configuration is needed just to get external displays working
- The NVIDIA driver handles GPU compute/rendering but does not own the display connectors

The current system correctly shows `OpenGL renderer: Mesa Intel Iris Xe` — the Intel path is active.

### 4.2 `appledisplay` Kernel Module

The Apple Cinema Display kernel driver is **already available** on this system:

```
/lib/modules/6.8.0-106-generic/kernel/drivers/usb/misc/appledisplay.ko.zst
```

It supports USB ID `05ac:921d` (exactly the 24" LED Cinema Display). It will **auto-load** when the display's USB cable is connected, and exposes brightness control via `/sys/class/backlight/`.

### 4.3 NVIDIA Driver Version

Installed: `nvidia-driver-580-open` (v580.126.09)

This is a recent driver. Known USB-C DisplayPort issues from driver versions ~465–535 are largely resolved in 580. The `nvidia-drm.modeset=1` kernel parameter should be set for correct PRIME/hybrid operation.

### 4.4 Dual Display via Daisy-Chaining

The Apple LED Cinema Display 24" **does not support DisplayPort MST (daisy-chaining)**. To drive two Cinema Displays simultaneously, each display requires its own dedicated USB-C port with DP Alt Mode. The XPS 15 9520 has at least 2 Thunderbolt 4 ports on the left side that support this.

---

## 5. Required Hardware

### Per Display
1. **USB-C to Mini DisplayPort adapter/cable** — one per display
   - Recommended: **UPTab USB-C to Mini DisplayPort 4K@60Hz** (~$25–35)
   - Alternative: **Plugable USB-C to DisplayPort Cable** (also well-regarded on Linux)
   - Must support **DisplayPort Alt Mode** — not a dock with DisplayLink chip
   - Passive adapters preferred over active; no driver required

2. **AC power cable** for each display (standard IEC C13 / "kettle lead")
   - The display is self-powered; MagSafe is irrelevant

3. **USB-A cable** from each display to the laptop (for audio, hub, brightness, webcam)
   - The display's cable bundle includes this

---

## 6. Software Requirements

### 6.1 Kernel Parameters (GRUB)
Add to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`:
```
nvidia-drm.modeset=1
```
Then: `sudo update-grub && sudo reboot`

### 6.2 Brightness Control
The `appledisplay` module (already present) should handle brightness automatically via sysfs backlight interface when USB is connected.

For manual control or fallback:
```bash
# Install build tools
sudo apt install build-essential libusb-dev

# Clone and build acdcontrol
git clone https://github.com/warvariuc/acdcontrol.git
cd acdcontrol && make

# Usage (0–255 range for 24" model):
sudo ./acdcontrol /dev/usb/hiddev0 200
```

Add udev rule for non-root access:
```
# /etc/udev/rules.d/10-apple-cinema.rules
SUBSYSTEMS=="usb", ATTRS{product}=="Apple LED Cinema Display", GROUP="users", MODE="0664"
```

### 6.3 iSight Webcam (Optional)
```bash
# Enable multiverse repository
sudo add-apt-repository multiverse
sudo apt update

# Install firmware extractor
sudo apt install isight-firmware-tools

# Extract firmware (requires AppleUSBVideoSupport file from Apple driver package)
sudo ift-extract -a /path/to/AppleUSBVideoSupport
# Installs to /lib/firmware/isight.fw
# Reboot or: sudo udevadm trigger
```

---

## 7. Known Issues & Workarounds

### 7.1 Suspend/Resume — Display Loses Signal
**Status:** Known, widespread issue across Linux + USB-C + external displays.
**Symptom:** After waking from sleep, the external display shows no signal.
**Workaround:** Physically unplug and replug the USB-C adapter after resume.
**Partial fix:** Create a systemd sleep hook to unbind/rebind the USB-C port:
```bash
# /etc/systemd/system/usbc-display-resume.service
[Unit]
Description=Rebind USB-C display on resume
After=suspend.target

[Service]
Type=oneshot
ExecStart=/usr/bin/xrandr --auto

[Install]
WantedBy=suspend.target
```

### 7.2 Display Detected but No Signal
If `xrandr` shows the output as connected but the screen is black:
```bash
xrandr --setprovideroutputsource NVIDIA-G0 modesetting
xrandr --auto
```

### 7.3 UCSI Warning in Kernel Log
The system shows:
```
workqueue: ucsi_handle_connector_change [typec_ucsi] hogged CPU for >10000us
```
This is a known cosmetic warning in kernel 6.8 related to USB-C connector event handling. It does not affect functionality.

### 7.4 Display Not Detected on First Connection
Force re-detection:
```bash
xrandr --auto
# or explicitly:
xrandr --output DP-1 --mode 1920x1200 --rate 60.00
```

---

## 8. CLI Application — Proposed Design

### Goal
A simple CLI tool that guides users through installing and configuring Apple Cinema Displays on Ubuntu.

### Proposed Feature Set

```
cinema-display-setup [COMMAND]

Commands:
  detect          Scan for connected Apple Cinema Displays (USB + xrandr)
  check           Verify system requirements (GPU driver, kernel params, modules)
  install         Install required packages and apply configuration
  configure       Run interactive display arrangement setup (xrandr)
  brightness      Get/set brightness on connected displays
  fix-resume      Install suspend/resume workaround service
  status          Show current display configuration and health
```

### Implementation Approach

**Language:** Bash script (no dependencies) or Python 3 (better UX with rich/curses)

**Detection Logic:**
1. `lsusb | grep "05ac:921d"` — detect Apple Cinema Display USB connection
2. `xrandr --query` — identify active DP outputs
3. `/sys/class/backlight/` — check appledisplay module loaded

**Check Logic:**
- Verify `nvidia-drm.modeset=1` in `/proc/cmdline`
- Check `appledisplay` module is available: `modinfo appledisplay`
- Check USB-C ports support DP Alt Mode: `/sys/class/typec/portN-partner/number_of_alternate_modes`

**Install Logic:**
- `modprobe appledisplay` (if not auto-loaded)
- Add udev rule for non-root brightness access
- Set GRUB kernel parameter
- Optionally install `isight-firmware-tools` from multiverse

**Configuration Logic:**
- List detected outputs from `xrandr`
- Interactive prompt: mirror or extend? position relative to laptop screen?
- Generate and apply `xrandr` commands
- Optionally persist to `~/.xprofile` or a startup script

### Technical Complexity: **Low–Medium**

All operations are standard Linux system administration. The main complexity is handling the variety of adapter types and GPU driver configurations across different machines.

---

## 9. Step-by-Step: Getting Displays Working Now

### Step 1: Hardware Connection
```
Laptop USB-C port (left, Thunderbolt 4)
    └── USB-C to Mini DisplayPort adapter
         └── Cinema Display #1 (Mini DP in)

Laptop USB-C port (left or right, second TB4 port)
    └── USB-C to Mini DisplayPort adapter
         └── Cinema Display #2 (Mini DP in)

Each display's USB-A cable → available USB-A port on laptop (for brightness/audio/hub)
Each display's AC cable → wall power (MagSafe left unplugged)
```

### Step 2: GRUB Parameter (if not already set)
```bash
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash nvidia-drm.modeset=1"/' /etc/default/grub
sudo update-grub
# Reboot required
```

### Step 3: Verify After Connection
```bash
# Check USB detection
lsusb | grep -i apple

# Check display detection
xrandr --query

# Check appledisplay module
lsmod | grep appledisplay

# Apply auto layout
xrandr --auto
```

### Step 4: Manual Layout Example
```bash
# Place Display #1 to the right of laptop, Display #2 to the right of Display #1
xrandr \
  --output eDP-1 --primary --mode 1920x1200 --pos 0x0 \
  --output DP-1 --mode 1920x1200 --pos 1920x0 \
  --output DP-2 --mode 1920x1200 --pos 3840x0
```

---

## 10. Sources

- [Apple LED Cinema Display specs — EveryMac.com](https://everymac.com/monitors/apple/studio_cinema/specs/apple-led-cinema-display-24-inch-specs.html)
- [Apple display brightness controls on Ubuntu — Dionysopoulos.me](https://www.dionysopoulos.me/apple-display-brightness-controls-in-ubuntu-desktop.html)
- [acdcontrol — GitHub (warvariuc fork)](https://github.com/warvariuc/acdcontrol)
- [CONFIG_USB_APPLEDISPLAY — Linux Kernel Driver DB](https://cateee.net/lkddb/web-lkddb/USB_APPLEDISPLAY.html)
- [isight-firmware-tools — Ubuntu Launchpad](https://launchpad.net/ubuntu/+source/isight-firmware-tools)
- [Dell XPS 15 External Display Guide — Dell Support](https://www.dell.com/support/manuals/en-us/xps-15-9520-laptop/)
- [XPS 9520 USB-C no signal — Dell Community Forums](https://www.dell.com/community/en/conversations/xps/xps-9520-external-monitor-usb-c-no-signal/)
- [Dell XPS 15 — ArchWiki](https://wiki.archlinux.org/title/Dell_XPS_15)
- [NVIDIA Optimus — ArchWiki](https://wiki.archlinux.org/title/NVIDIA_Optimus)
- [USB-C DisplayPort issues — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/usb-c-displayport-not-working-since-465-24-02/176780)
- [Cannot connect Apple Cinema Display via DisplayPort — Framework Community](https://community.frame.work/t/cannot-connect-apple-cinema-display-through-displayport/62260)
- [Apple Cinema Display — linux-hardware.org](https://linux-hardware.org/?id=usb:05ac-921d)
- [UPTab USB-C to Mini DisplayPort adapter](https://www.uptab.com/products/usb-c-to-mini-displayport-adapter-4k-60hz-silver)
