#!/usr/bin/env python3
"""
cinema_display_setup.py — Apple Cinema Display setup tool for Ubuntu 24
Target: Dell XPS 15 9520 + Apple LED Cinema Display 24" (A1267) via USB-C → Mini DP

Usage:
  python3 cinema_display_setup.py            # interactive menu
  python3 cinema_display_setup.py --diagnose  # diagnose only
  python3 cinema_display_setup.py --fix       # auto-fix everything
  python3 cinema_display_setup.py --brightness N   # set brightness 0-100
  python3 cinema_display_setup.py --apply-layout   # apply saved layout
"""

import os
import re
import sys
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 1] Constants & Config
# ─────────────────────────────────────────────────────────────────────────────

APPLE_CINEMA_USB_ID = "05ac:921d"
APPLE_CINEMA_PRODUCT_NAME = "Apple LED Cinema Display"
CINEMA_RESOLUTION = "1920x1200"

GRUB_PATH = Path("/etc/default/grub")
UDEV_RULE_PATH = Path("/etc/udev/rules.d/10-apple-cinema-display.rules")
SYSTEMD_SERVICE_PATH = Path("/etc/systemd/system/apple-cinema-resume.service")
BACKLIGHT_PATH = Path("/sys/class/backlight/apple_backlight")
TYPEC_PATH = Path("/sys/class/typec")

XPROFILE_PATH = Path.home() / ".xprofile"
CONFIG_DIR = Path.home() / ".config" / "cinema-display-setup"
CONFIG_PATH = CONFIG_DIR / "config.json"

UDEV_RULE_CONTENT = (
    'SUBSYSTEMS=="usb", ATTRS{product}=="Apple LED Cinema Display", '
    'GROUP="users", MODE="0664"\n'
)

SYSTEMD_SERVICE_CONTENT = """\
[Unit]
Description=Restore Apple Cinema Display after suspend
After=suspend.target hibernate.target hybrid-sleep.target

[Service]
Type=oneshot
Environment=DISPLAY=:0
Environment=XAUTHORITY=/run/user/1000/gdm/Xauthority
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/xrandr --auto

[Install]
WantedBy=suspend.target hibernate.target
"""

# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 8] Utilities (defined early — used throughout)
# ─────────────────────────────────────────────────────────────────────────────

def run_cmd(args: list, input_data: str = None) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            input=input_data,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out: {' '.join(args)}"


def run_sudo_cmd(args: list, reason: str = "") -> tuple[int, str, str]:
    """Run a command with sudo, letting stdin/stderr pass through to the terminal
    so password prompts are visible and interactive. stdout is captured."""
    if reason:
        cprint(f"[sudo] {reason}", "yellow")
    try:
        result = subprocess.run(
            ["sudo"] + args,
            stdout=subprocess.PIPE,
            stderr=None,   # inherit — sudo password prompt goes to terminal
            stdin=None,    # inherit — user can type password
            text=True,
            timeout=60,
        )
        return result.returncode, result.stdout or "", ""
    except FileNotFoundError:
        return 1, "", f"Command not found: sudo"
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out: sudo {' '.join(args)}"


def confirm(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question, return True for yes."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{prompt} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def read_file_text(path: Path) -> Optional[str]:
    """Read a file's text, return None on error."""
    try:
        return path.read_text()
    except (OSError, PermissionError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Rich / fallback output
# ─────────────────────────────────────────────────────────────────────────────

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import print as rprint

    _console = Console()
    RICH_AVAILABLE = True

    def cprint(msg: str, style: str = "") -> None:
        _console.print(msg, style=style)

    def print_panel(title: str, content: str, style: str = "bold cyan") -> None:
        _console.print(Panel(content, title=title, border_style=style))

    def print_header(text: str) -> None:
        _console.print(f"\n[bold cyan]{text}[/bold cyan]")

    def status_ok(msg: str) -> None:
        _console.print(f"  [green][✓][/green] {msg}")

    def status_fail(msg: str) -> None:
        _console.print(f"  [red][✗][/red] {msg}")

    def status_warn(msg: str) -> None:
        _console.print(f"  [yellow][!][/yellow] {msg}")

    def status_info(msg: str) -> None:
        _console.print(f"  [blue][i][/blue] {msg}")

except ImportError:
    RICH_AVAILABLE = False
    ANSI = {
        "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
        "blue": "\033[34m", "cyan": "\033[36m", "bold": "\033[1m",
        "reset": "\033[0m",
    }

    def _a(color: str, text: str) -> str:
        return f"{ANSI.get(color, '')}{text}{ANSI['reset']}"

    def cprint(msg: str, style: str = "") -> None:
        # Strip rich markup tags for fallback
        clean = re.sub(r"\[/?[^\]]+\]", "", msg)
        print(clean)

    def print_panel(title: str, content: str, style: str = "") -> None:
        width = 60
        print(_a("cyan", "╔" + "═" * (width - 2) + "╗"))
        print(_a("cyan", f"║  {title:<{width-4}}║"))
        print(_a("cyan", "╠" + "═" * (width - 2) + "╣"))
        for line in content.splitlines():
            print(_a("cyan", f"║  {line:<{width-4}}║"))
        print(_a("cyan", "╚" + "═" * (width - 2) + "╝"))

    def print_header(text: str) -> None:
        print(f"\n{_a('cyan', _a('bold', text))}")

    def status_ok(msg: str) -> None:
        print(f"  {_a('green', '[✓]')} {msg}")

    def status_fail(msg: str) -> None:
        print(f"  {_a('red', '[✗]')} {msg}")

    def status_warn(msg: str) -> None:
        print(f"  {_a('yellow', '[!]')} {msg}")

    def status_info(msg: str) -> None:
        print(f"  {_a('blue', '[i]')} {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 2] Detection Layer
# ─────────────────────────────────────────────────────────────────────────────

def detect_apple_displays_usb() -> list[dict]:
    """Parse lsusb output to find Apple Cinema Display devices."""
    rc, out, _ = run_cmd(["lsusb"])
    displays = []
    for line in out.splitlines():
        if APPLE_CINEMA_USB_ID in line or "Apple LED Cinema" in line:
            displays.append({"raw": line.strip(), "usb_id": APPLE_CINEMA_USB_ID})
    return displays


def detect_connected_outputs() -> list[dict]:
    """Parse xrandr to find connected display outputs."""
    rc, out, err = run_cmd(["xrandr", "--query"])
    if rc != 0:
        return []
    outputs = []
    current_output = None
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+(connected|disconnected)\s*(primary\s*)?(\d+x\d+\+\d+\+\d+)?", line)
        if m:
            name = m.group(1)
            connected = m.group(2) == "connected"
            is_primary = bool(m.group(3))
            current_res = m.group(4)
            current_output = {
                "name": name,
                "connected": connected,
                "primary": is_primary,
                "active_res": current_res,
                "modes": [],
            }
            outputs.append(current_output)
        elif current_output and re.match(r"^\s+\d+x\d+", line):
            mode_m = re.match(r"\s+(\d+x\d+)", line)
            if mode_m:
                current_output["modes"].append(mode_m.group(1))
    return outputs


def detect_appledisplay_module() -> dict:
    """Check if the appledisplay kernel module is available and loaded."""
    rc_info, out_info, _ = run_cmd(["modinfo", "appledisplay"])
    available = rc_info == 0

    rc_mod, out_mod, _ = run_cmd(["lsmod"])
    loaded = "appledisplay" in out_mod

    return {"available": available, "loaded": loaded}


def detect_backlight() -> Optional[dict]:
    """Check sysfs backlight for apple_backlight."""
    if not BACKLIGHT_PATH.exists():
        return None
    max_path = BACKLIGHT_PATH / "max_brightness"
    cur_path = BACKLIGHT_PATH / "brightness"
    try:
        max_b = int((max_path).read_text().strip())
        cur_b = int((cur_path).read_text().strip())
        return {"current": cur_b, "max": max_b, "path": str(BACKLIGHT_PATH)}
    except (OSError, ValueError):
        return None


def detect_wayland() -> bool:
    """Return True if running under Wayland."""
    return os.environ.get("WAYLAND_DISPLAY") is not None


def detect_display_server() -> str:
    """Return 'wayland', 'x11', or 'unknown'."""
    if detect_wayland():
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def detect_connected_edp() -> Optional[dict]:
    """Find the laptop's built-in screen (eDP)."""
    for out in detect_connected_outputs():
        if out["name"].startswith("eDP") and out["connected"]:
            return out
    return None


def detect_cinema_display_output() -> Optional[dict]:
    """Find a connected external output that looks like the Cinema Display."""
    outputs = detect_connected_outputs()
    for out in outputs:
        if out["connected"] and not out["name"].startswith("eDP"):
            if CINEMA_RESOLUTION in out["modes"] or (
                out["active_res"] and CINEMA_RESOLUTION in out["active_res"]
            ):
                return out
    # If nothing matches by resolution, return first connected non-eDP
    for out in outputs:
        if out["connected"] and not out["name"].startswith("eDP"):
            return out
    return None


# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 3] Diagnosis Layer
# ─────────────────────────────────────────────────────────────────────────────

class Issue:
    def __init__(self, key: str, title: str, description: str,
                 fix_fn=None, severity: str = "error"):
        self.key = key
        self.title = title
        self.description = description
        self.fix_fn = fix_fn
        self.severity = severity  # "error", "warning", "info"


def check_nvidia_modeset() -> Optional[Issue]:
    """Check if nvidia-drm.modeset=1 is in /proc/cmdline."""
    cmdline = read_file_text(Path("/proc/cmdline")) or ""
    if "nvidia-drm.modeset=1" in cmdline:
        return None
    return Issue(
        key="nvidia_modeset",
        title="nvidia-drm.modeset=1 not set",
        description=(
            "The NVIDIA DRM modesetting parameter is missing from the kernel "
            "command line. This is the primary cause of USB-C DisplayPort "
            "connections failing on Optimus laptops. A GRUB edit + reboot is required."
        ),
        fix_fn=fix_grub_nvidia_modeset,
        severity="error",
    )


def check_appledisplay_module() -> Optional[Issue]:
    """Check if appledisplay module is available."""
    mod = detect_appledisplay_module()
    if not mod["available"]:
        return Issue(
            key="no_appledisplay_module",
            title="appledisplay kernel module not available",
            description=(
                "The appledisplay.ko module is not present on this kernel. "
                "Brightness control will not be available."
            ),
            severity="warning",
        )
    if not mod["loaded"]:
        return Issue(
            key="appledisplay_not_loaded",
            title="appledisplay module not loaded",
            description=(
                "The appledisplay module is available but not loaded. "
                "It normally auto-loads when the display's USB cable is connected, "
                "but can be loaded manually."
            ),
            fix_fn=fix_load_appledisplay,
            severity="warning",
        )
    return None


def check_udev_rules() -> Optional[Issue]:
    """Check if the udev brightness rule is installed."""
    if UDEV_RULE_PATH.exists():
        content = read_file_text(UDEV_RULE_PATH) or ""
        if "Apple LED Cinema Display" in content:
            return None
    return Issue(
        key="no_udev_rule",
        title="udev brightness rule not installed",
        description=(
            f"No udev rule found at {UDEV_RULE_PATH}. Without this rule, "
            "non-root users cannot control brightness via the sysfs interface."
        ),
        fix_fn=fix_udev_brightness_rule,
        severity="warning",
    )


def check_suspend_resume_hook() -> Optional[Issue]:
    """Check if the suspend/resume systemd service is installed."""
    if SYSTEMD_SERVICE_PATH.exists():
        return None
    return Issue(
        key="no_suspend_hook",
        title="suspend/resume hook not installed",
        description=(
            "After waking from suspend, the external display often loses signal. "
            "A systemd service can automatically run xrandr --auto on resume."
        ),
        fix_fn=fix_suspend_resume_hook,
        severity="warning",
    )


def check_grub_params() -> Optional[Issue]:
    """Check current GRUB_CMDLINE_LINUX_DEFAULT for expected params."""
    grub_text = read_file_text(GRUB_PATH)
    if not grub_text:
        return Issue(
            key="grub_unreadable",
            title="Cannot read /etc/default/grub",
            description="The GRUB configuration file is missing or unreadable.",
            severity="error",
        )
    # Check if already in cmdline
    m = re.search(r'GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', grub_text)
    if m and "nvidia-drm.modeset=1" in m.group(1):
        return None  # already set in GRUB (though maybe not in effect yet)
    return None  # check_nvidia_modeset handles the /proc/cmdline check


def run_full_diagnosis() -> list[Issue]:
    """Run all checks and return list of Issues found."""
    issues = []
    checks = [
        check_nvidia_modeset,
        check_appledisplay_module,
        check_udev_rules,
        check_suspend_resume_hook,
    ]
    for check in checks:
        issue = check()
        if issue:
            issues.append(issue)
    return issues


# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 4] Fix Layer
# ─────────────────────────────────────────────────────────────────────────────

_reboot_required = False


def fix_grub_nvidia_modeset() -> bool:
    """Edit /etc/default/grub to add nvidia-drm.modeset=1, then run update-grub."""
    global _reboot_required

    grub_text = read_file_text(GRUB_PATH)
    if grub_text is None:
        cprint("[red]Cannot read /etc/default/grub[/red]")
        return False

    # Backup
    backup_path = Path("/etc/default/grub.bak.cinema-display")
    rc, _, err = run_sudo_cmd(
        ["cp", str(GRUB_PATH), str(backup_path)],
        reason=f"Back up {GRUB_PATH} before editing",
    )
    if rc != 0:
        cprint(f"[red]Failed to back up GRUB file: {err}[/red]")
        return False

    # Find and edit the CMDLINE_LINUX_DEFAULT line
    def add_param(m):
        current = m.group(1)
        if "nvidia-drm.modeset=1" in current:
            return m.group(0)  # already present
        new_val = current.rstrip() + " nvidia-drm.modeset=1"
        return f'GRUB_CMDLINE_LINUX_DEFAULT="{new_val}"'

    new_text = re.sub(
        r'GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"',
        add_param,
        grub_text,
    )

    if new_text == grub_text:
        # Pattern didn't match; append a new line
        new_text += '\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash nvidia-drm.modeset=1"\n'

    # Write via tee (sudo) — stdout suppressed, stderr/stdin inherited for password prompt
    cprint("[sudo] Write updated GRUB_CMDLINE_LINUX_DEFAULT", "yellow")
    try:
        result = subprocess.run(
            ["sudo", "tee", str(GRUB_PATH)],
            input=new_text,
            stdout=subprocess.DEVNULL,
            stderr=None,
            text=True,
        )
        if result.returncode != 0:
            cprint("[red]Failed to write GRUB file (sudo tee returned non-zero)[/red]")
            return False
    except Exception as e:
        cprint(f"[red]Error writing GRUB file: {e}[/red]")
        return False

    cprint("[green]  → GRUB file updated[/green]")

    # Run update-grub
    cprint("  → Running update-grub...")
    rc, out, err = run_sudo_cmd(["update-grub"], reason="Regenerate GRUB boot configuration")
    if rc != 0:
        cprint(f"[yellow]  update-grub failed (rc={rc}): {err}[/yellow]")
        cprint("[yellow]  You may need to run 'sudo update-grub' manually.[/yellow]")
        return False

    cprint("[green]  → update-grub completed[/green]")
    _reboot_required = True
    return True


def fix_load_appledisplay() -> bool:
    """Load the appledisplay kernel module."""
    rc, _, err = run_sudo_cmd(
        ["modprobe", "appledisplay"],
        reason="Load appledisplay kernel module for brightness control",
    )
    if rc != 0:
        cprint(f"[red]  modprobe failed: {err}[/red]")
        return False
    cprint("[green]  → appledisplay module loaded[/green]")
    return True


def fix_udev_brightness_rule() -> bool:
    """Write the udev rule for non-root brightness access."""
    cprint(f"[sudo] Write udev rule to {UDEV_RULE_PATH}", "yellow")
    try:
        result = subprocess.run(
            ["sudo", "tee", str(UDEV_RULE_PATH)],
            input=UDEV_RULE_CONTENT,
            stdout=subprocess.DEVNULL,
            stderr=None,
            text=True,
        )
        if result.returncode != 0:
            cprint("[red]  Failed to write udev rule (sudo tee returned non-zero)[/red]")
            return False
    except Exception as e:
        cprint(f"[red]  Error writing udev rule: {e}[/red]")
        return False

    # Reload udev rules
    run_sudo_cmd(["udevadm", "control", "--reload-rules"], reason="Reload udev rules")
    run_sudo_cmd(["udevadm", "trigger"], reason="Trigger udev")
    cprint(f"[green]  → udev rule written to {UDEV_RULE_PATH}[/green]")
    return True


def fix_suspend_resume_hook() -> bool:
    """Install systemd service for suspend/resume display recovery."""
    cprint(f"[sudo] Write systemd service to {SYSTEMD_SERVICE_PATH}", "yellow")
    try:
        result = subprocess.run(
            ["sudo", "tee", str(SYSTEMD_SERVICE_PATH)],
            input=SYSTEMD_SERVICE_CONTENT,
            stdout=subprocess.DEVNULL,
            stderr=None,
            text=True,
        )
        if result.returncode != 0:
            cprint("[red]  Failed to write service (sudo tee returned non-zero)[/red]")
            return False
    except Exception as e:
        cprint(f"[red]  Error writing service: {e}[/red]")
        return False

    rc, _, err = run_sudo_cmd(
        ["systemctl", "enable", "apple-cinema-resume.service"],
        reason="Enable suspend/resume hook service",
    )
    if rc != 0:
        cprint(f"[yellow]  systemctl enable failed: {err}[/yellow]")
        return False
    cprint(f"[green]  → Suspend/resume service installed at {SYSTEMD_SERVICE_PATH}[/green]")
    return True


def fix_force_xrandr_detect() -> bool:
    """Try to force xrandr to detect the display without rebooting."""
    ds = detect_display_server()
    if ds == "wayland":
        cprint("[yellow]  Wayland session — xrandr --auto not applicable[/yellow]")
        return False
    if ds == "unknown":
        cprint("[yellow]  No display server detected ($DISPLAY not set)[/yellow]")
        return False

    cprint("  → Trying xrandr PRIME provider setup...")
    run_cmd(["xrandr", "--setprovideroutputsource", "NVIDIA-G0", "modesetting"])

    cprint("  → Running xrandr --auto...")
    rc, out, err = run_cmd(["xrandr", "--auto"])
    if rc == 0:
        cprint("[green]  → xrandr --auto succeeded[/green]")
        # Check if any new outputs appeared
        outputs = detect_connected_outputs()
        connected = [o for o in outputs if o["connected"] and not o["name"].startswith("eDP")]
        if connected:
            cprint(f"[green]  → External display detected: {', '.join(o['name'] for o in connected)}[/green]")
        return True
    else:
        cprint(f"[yellow]  xrandr --auto returned rc={rc}: {err}[/yellow]")
        return False


def auto_fix_all(issues: list[Issue]) -> bool:
    """Run fix functions for all fixable issues. Returns True if reboot needed."""
    global _reboot_required
    _reboot_required = False

    fixable = [i for i in issues if i.fix_fn]
    if not fixable:
        cprint("[green]No fixable issues found.[/green]")
        return False

    for issue in fixable:
        cprint(f"\n  → Fixing: {issue.title}")
        success = issue.fix_fn()
        if not success:
            cprint(f"[yellow]  Fix for '{issue.title}' may not have completed.[/yellow]")

    # Always try immediate xrandr fix
    cprint("\n  → Attempting immediate display detection...")
    fix_force_xrandr_detect()

    return _reboot_required


# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 5] Configuration Layer
# ─────────────────────────────────────────────────────────────────────────────

def get_all_outputs() -> list[dict]:
    """Return all connected outputs from xrandr."""
    return [o for o in detect_connected_outputs() if o["connected"]]


def get_external_outputs() -> list[dict]:
    """Return connected non-eDP outputs."""
    return [o for o in get_all_outputs() if not o["name"].startswith("eDP")]


def apply_xrandr_layout(layout: str, laptop_out: str, ext_out: str) -> bool:
    """Build and apply an xrandr command for a given layout."""
    laptop_res = "1920x1200"
    ext_res = CINEMA_RESOLUTION

    if layout == "right":
        cmd = [
            "xrandr",
            "--output", laptop_out, "--primary", "--mode", laptop_res, "--pos", "0x0",
            "--output", ext_out, "--mode", ext_res, "--pos", "1920x0",
        ]
    elif layout == "left":
        cmd = [
            "xrandr",
            "--output", laptop_out, "--primary", "--mode", laptop_res, "--pos", "1920x0",
            "--output", ext_out, "--mode", ext_res, "--pos", "0x0",
        ]
    elif layout == "above":
        cmd = [
            "xrandr",
            "--output", laptop_out, "--primary", "--mode", laptop_res, "--pos", "0x1200",
            "--output", ext_out, "--mode", ext_res, "--pos", "0x0",
        ]
    elif layout == "mirror":
        cmd = [
            "xrandr",
            "--output", laptop_out, "--primary", "--mode", laptop_res, "--pos", "0x0",
            "--output", ext_out, "--mode", ext_res, "--pos", "0x0", "--same-as", laptop_out,
        ]
    elif layout == "cinema_only":
        cmd = [
            "xrandr",
            "--output", laptop_out, "--off",
            "--output", ext_out, "--primary", "--mode", ext_res, "--pos", "0x0",
        ]
    elif layout == "laptop_only":
        cmd = [
            "xrandr",
            "--output", laptop_out, "--primary", "--mode", laptop_res, "--pos", "0x0",
            "--output", ext_out, "--off",
        ]
    else:
        cprint(f"[red]Unknown layout: {layout}[/red]")
        return False

    rc, out, err = run_cmd(cmd)
    if rc != 0:
        cprint(f"[red]xrandr failed: {err}[/red]")
        return False
    return True


def persist_layout_to_profile(layout: str, laptop_out: str, ext_out: str) -> bool:
    """Write the xrandr command to ~/.xprofile for auto-apply on login."""
    laptop_res = "1920x1200"
    ext_res = CINEMA_RESOLUTION
    marker_start = "# Apple Cinema Display layout — managed by cinema-display-setup"
    marker_end = "# end cinema-display-setup"

    layout_cmds = {
        "right": (
            f"xrandr --output {laptop_out} --primary --mode {laptop_res} --pos 0x0 \\\n"
            f"       --output {ext_out} --mode {ext_res} --pos 1920x0"
        ),
        "left": (
            f"xrandr --output {laptop_out} --primary --mode {laptop_res} --pos 1920x0 \\\n"
            f"       --output {ext_out} --mode {ext_res} --pos 0x0"
        ),
        "above": (
            f"xrandr --output {laptop_out} --primary --mode {laptop_res} --pos 0x1200 \\\n"
            f"       --output {ext_out} --mode {ext_res} --pos 0x0"
        ),
        "mirror": (
            f"xrandr --output {laptop_out} --primary --mode {laptop_res} --pos 0x0 \\\n"
            f"       --output {ext_out} --mode {ext_res} --same-as {laptop_out}"
        ),
        "cinema_only": (
            f"xrandr --output {laptop_out} --off \\\n"
            f"       --output {ext_out} --primary --mode {ext_res} --pos 0x0"
        ),
        "laptop_only": (
            f"xrandr --output {laptop_out} --primary --mode {laptop_res} --pos 0x0 \\\n"
            f"       --output {ext_out} --off"
        ),
    }

    new_block = f"{marker_start}\n{layout_cmds.get(layout, '')}\n{marker_end}\n"

    existing = read_file_text(XPROFILE_PATH) or ""
    # Remove old block if present
    cleaned = re.sub(
        rf"{re.escape(marker_start)}.*?{re.escape(marker_end)}\n",
        "",
        existing,
        flags=re.DOTALL,
    )
    updated = cleaned.rstrip("\n") + "\n" + new_block

    try:
        XPROFILE_PATH.write_text(updated)
        return True
    except OSError as e:
        cprint(f"[red]Failed to write {XPROFILE_PATH}: {e}[/red]")
        return False


def configure_layout_interactive() -> None:
    """Interactive display layout configuration menu."""
    ds = detect_display_server()
    if ds == "wayland":
        cprint("[yellow]Wayland detected — xrandr layout configuration requires X11.[/yellow]")
        cprint("[yellow]Consider switching to an X11 session or use 'gnome-randr'.[/yellow]")
        return

    all_outputs = get_all_outputs()
    if not all_outputs:
        cprint("[yellow]No connected displays detected by xrandr.[/yellow]")
        return

    edp_list = [o for o in all_outputs if o["name"].startswith("eDP")]
    ext_list = [o for o in all_outputs if not o["name"].startswith("eDP")]

    print_header("Configure Display Layout")
    cprint("\nConnected displays:")
    for i, o in enumerate(all_outputs, 1):
        kind = "Laptop screen" if o["name"].startswith("eDP") else "External display"
        res_info = o["active_res"] or (o["modes"][0] if o["modes"] else "?")
        cprint(f"  {i}. {o['name']:<8} {kind:<20} {res_info}")

    if not ext_list:
        cprint("\n[yellow]No external displays detected. Connect the Cinema Display and try again.[/yellow]")
        return

    laptop_out = edp_list[0]["name"] if edp_list else all_outputs[0]["name"]
    ext_out = ext_list[0]["name"]

    cprint(f"\nLaptop output: {laptop_out}")
    cprint(f"External output: {ext_out}")

    layout_options = [
        ("right",       "Extend — Cinema Display to the RIGHT of laptop"),
        ("left",        "Extend — Cinema Display to the LEFT of laptop"),
        ("above",       "Extend — Cinema Display ABOVE laptop"),
        ("mirror",      "Mirror — same image on both screens"),
        ("cinema_only", "Cinema Display ONLY (laptop screen off)"),
        ("laptop_only", "Laptop ONLY (Cinema Display off)"),
    ]

    cprint("\nLayout options:")
    for i, (key, label) in enumerate(layout_options, 1):
        cprint(f"  {i}. {label}")
    cprint("  7. Back")

    try:
        choice = input("\nChoice [1-7]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == "7" or not choice:
        return

    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(layout_options)):
            cprint("[red]Invalid choice.[/red]")
            return
    except ValueError:
        cprint("[red]Invalid input.[/red]")
        return

    layout_key, layout_label = layout_options[idx]
    cprint(f"\n  → Applying: {layout_label}")
    success = apply_xrandr_layout(layout_key, laptop_out, ext_out)
    if success:
        cprint("[green]  → Layout applied.[/green]")
        if confirm("\nSave this layout for auto-apply on login?"):
            if persist_layout_to_profile(layout_key, laptop_out, ext_out):
                cprint(f"[green]  → Layout saved to {XPROFILE_PATH}[/green]")
            save_config({"layout": layout_key, "laptop_output": laptop_out, "ext_output": ext_out})
    else:
        cprint("[red]  → Failed to apply layout.[/red]")


# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 6] Brightness Control
# ─────────────────────────────────────────────────────────────────────────────

def get_brightness() -> Optional[dict]:
    """Read current brightness from sysfs. Returns {current, max, pct} or None."""
    info = detect_backlight()
    if info is None:
        return None
    pct = round(info["current"] / info["max"] * 100) if info["max"] > 0 else 0
    return {"current": info["current"], "max": info["max"], "pct": pct}


def set_brightness(pct: int) -> bool:
    """Set brightness as a percentage (0–100)."""
    info = detect_backlight()
    if info is None:
        cprint("[yellow]appledisplay backlight not available.[/yellow]")
        cprint("[yellow]Ensure the appledisplay module is loaded and USB cable is connected.[/yellow]")
        return False

    pct = max(0, min(100, pct))
    raw = round(pct / 100.0 * info["max"])
    cur_path = BACKLIGHT_PATH / "brightness"

    # Try direct write first (works if user has udev rule)
    try:
        cur_path.write_text(str(raw))
        return True
    except PermissionError:
        pass

    # Fall back to sudo tee
    result = subprocess.run(
        ["sudo", "tee", str(cur_path)],
        input=str(raw),
        stdout=subprocess.DEVNULL,
        stderr=None,
        stdin=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        cprint("[red]Failed to set brightness (sudo tee returned non-zero)[/red]")
        return False
    return True


def brightness_menu() -> None:
    """Interactive brightness control."""
    print_header("Brightness Control")

    bl = get_brightness()
    if bl is None:
        cprint("[yellow]Apple backlight not available.[/yellow]")
        cprint("[yellow]Requirements:[/yellow]")
        cprint("  1. appledisplay kernel module loaded (run diagnosis to fix)")
        cprint("  2. USB cable from Cinema Display connected to laptop")
        return

    def show_current():
        bl = get_brightness()
        if bl is None:
            return
        bar_len = 30
        filled = round(bl["pct"] / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        cprint(f"\n  Current: {bl['pct']}%  [{bar}]")

    show_current()
    cprint("\n  Enter a number (0-100), +/- to adjust by 10, or q to go back")

    while True:
        try:
            raw = input("\n  Brightness [0-100/+/-/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if raw == "q" or raw == "":
            return
        elif raw == "+":
            bl = get_brightness()
            if bl:
                new_pct = min(100, bl["pct"] + 10)
                if set_brightness(new_pct):
                    show_current()
        elif raw == "-":
            bl = get_brightness()
            if bl:
                new_pct = max(0, bl["pct"] - 10)
                if set_brightness(new_pct):
                    show_current()
        else:
            try:
                val = int(raw)
                if set_brightness(val):
                    show_current()
                    save_config({"brightness": val})
                else:
                    cprint("[red]  Failed to set brightness.[/red]")
            except ValueError:
                cprint("[red]  Invalid input. Enter a number 0-100, +, -, or q.[/red]")


# ─────────────────────────────────────────────────────────────────────────────
# Config persistence
# ─────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def save_config(updates: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config.update(updates)
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# [SECTION 7] Main Menu & Status Banner
# ─────────────────────────────────────────────────────────────────────────────

def show_status_banner() -> None:
    """Display a rich panel showing current display and USB state."""
    usb_displays = detect_apple_displays_usb()
    outputs = detect_connected_outputs()
    edp = next((o for o in outputs if o["name"].startswith("eDP") and o["connected"]), None)
    ext_outputs = [o for o in outputs if o["connected"] and not o["name"].startswith("eDP")]
    all_ext = [o for o in outputs if not o["name"].startswith("eDP")]
    ds = detect_display_server()
    bl = get_brightness()

    # Build banner content
    lines = []

    # Laptop screen
    if edp:
        res = edp["active_res"] or (edp["modes"][0] if edp["modes"] else "?")
        lines.append(f"  Laptop screen:    {edp['name']:<8} {res}  ✓ active")
    else:
        lines.append("  Laptop screen:    not detected")

    # External outputs
    if ext_outputs:
        for o in ext_outputs:
            res = o["active_res"] or (o["modes"][0] if o["modes"] else "?")
            lines.append(f"  External display: {o['name']:<8} {res}  ✓ connected")
    elif all_ext:
        names = ", ".join(o["name"] for o in all_ext[:4])
        lines.append(f"  External display: {names}  — NOT ACTIVE")
    else:
        lines.append("  External display: NOT DETECTED")

    # USB
    if usb_displays:
        lines.append(f"  USB (Cinema):     CONNECTED  ({APPLE_CINEMA_USB_ID})")
    else:
        lines.append("  USB (Cinema):     NOT CONNECTED")

    # Brightness
    if bl:
        lines.append(f"  Brightness:       {bl['pct']}%")
    else:
        lines.append("  Brightness:       N/A (backlight not active)")

    # Display server
    lines.append(f"  Session:          {ds.upper()}")

    content = "\n".join(lines)
    print_panel("Apple Cinema Display Setup — Ubuntu 24", content)


def show_diagnosis_menu() -> None:
    """Run diagnosis and offer to auto-fix."""
    print_header("Diagnosis")
    cprint("\nChecking system...")

    issues = run_full_diagnosis()

    if not issues:
        status_ok("No issues found — system appears correctly configured.")
        usb = detect_apple_displays_usb()
        ext = get_external_outputs()
        if not usb:
            status_warn("Cinema Display USB not detected. Connect the USB cable from the display.")
        if not ext:
            status_warn("No external display active in xrandr.")
            if not usb:
                cprint("\n[cyan]State A:[/cyan] Neither USB nor video signal detected.")
                cprint("  → Check physical connections (USB-C adapter, USB-A cable, power).")
            else:
                cprint("\n[cyan]State C:[/cyan] USB connected but no video signal.")
                cprint("  → After fixing nvidia-drm.modeset=1 and rebooting, video should appear.")
        else:
            status_ok("Cinema Display video signal active.")
        return

    for issue in issues:
        if issue.severity == "error":
            status_fail(f"{issue.title}")
        else:
            status_warn(f"{issue.title}")
        cprint(f"     {issue.description}")

    fixable = [i for i in issues if i.fix_fn]
    if fixable:
        cprint(f"\n{len(fixable)} issue(s) can be fixed automatically.")
        if confirm("\nFix automatically?"):
            reboot_needed = auto_fix_all(issues)
            if reboot_needed:
                cprint("\n[yellow]⚠  A reboot is required for the display detection fix to take effect.[/yellow]")
                if confirm("Reboot now?", default=False):
                    run_sudo_cmd(["reboot"], reason="Reboot to apply kernel parameter changes")
    else:
        cprint("\n[yellow]No automatic fixes available. Manual steps required.[/yellow]")


def show_system_details() -> None:
    """Show detailed system information."""
    print_header("System Details")

    # xrandr
    cprint("\n[bold]xrandr outputs:[/bold]")
    rc, out, _ = run_cmd(["xrandr", "--query"])
    if rc == 0:
        for line in out.splitlines():
            if re.match(r"^\S+\s+(connected|disconnected)", line):
                cprint(f"  {line}")
    else:
        cprint("  [yellow]xrandr not available[/yellow]")

    # lsusb
    cprint("\n[bold]USB devices (Apple):[/bold]")
    rc, out, _ = run_cmd(["lsusb"])
    apple_lines = [l for l in out.splitlines() if "Apple" in l or "05ac" in l]
    if apple_lines:
        for l in apple_lines:
            cprint(f"  {l}")
    else:
        cprint("  No Apple USB devices detected")

    # appledisplay module
    cprint("\n[bold]appledisplay module:[/bold]")
    mod = detect_appledisplay_module()
    cprint(f"  Available: {mod['available']}")
    cprint(f"  Loaded:    {mod['loaded']}")

    # Kernel cmdline
    cprint("\n[bold]/proc/cmdline:[/bold]")
    cmdline = read_file_text(Path("/proc/cmdline")) or "(unreadable)"
    cprint(f"  {cmdline.strip()}")

    # Backlight
    cprint("\n[bold]Backlight:[/bold]")
    bl = get_brightness()
    if bl:
        cprint(f"  Path: {BACKLIGHT_PATH}")
        cprint(f"  Current: {bl['current']} / {bl['max']} ({bl['pct']}%)")
    else:
        cprint("  Not available (appledisplay not loaded or USB not connected)")

    # USB-C alt modes
    cprint("\n[bold]USB-C alt modes:[/bold]")
    if TYPEC_PATH.exists():
        for port in sorted(TYPEC_PATH.iterdir()):
            if "partner" in port.name:
                modes_path = port / "number_of_alternate_modes"
                if modes_path.exists():
                    modes = read_file_text(modes_path) or "?"
                    cprint(f"  {port.name}: {modes.strip()} alternate modes")
    else:
        cprint("  /sys/class/typec not available")

    # GRUB
    cprint("\n[bold]/etc/default/grub (CMDLINE_LINUX_DEFAULT):[/bold]")
    grub = read_file_text(GRUB_PATH) or ""
    m = re.search(r'GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', grub)
    if m:
        cprint(f"  {m.group(0)}")
    else:
        cprint("  (not found or unreadable)")


def show_isight_guide() -> None:
    """Show iSight webcam installation guide."""
    print_header("iSight Webcam Setup")
    guide = textwrap.dedent("""
    The Apple Cinema Display 24" includes an iSight webcam that requires
    proprietary firmware extraction on Linux.

    Steps:
    1. Enable multiverse repository:
         sudo add-apt-repository multiverse
         sudo apt update

    2. Install firmware extraction tool:
         sudo apt install isight-firmware-tools

    3. Obtain the Apple firmware file 'AppleUSBVideoSupport':
         - From a macOS system: /System/Library/Extensions/Apple_iSight.kext/
           Contents/Resources/AppleUSBVideoSupport
         - Or from an old Apple iSight installer package (.dmg)

    4. Extract the firmware:
         sudo ift-extract -a /path/to/AppleUSBVideoSupport
         # Installs to /lib/firmware/isight.fw

    5. Reconnect the display USB cable or run:
         sudo udevadm trigger

    The webcam should then appear as a V4L2 device.
    """)
    cprint(guide)


def apply_saved_layout() -> bool:
    """Load config and apply saved layout."""
    config = load_config()
    layout = config.get("layout")
    laptop = config.get("laptop_output")
    ext = config.get("ext_output")

    if not layout or not laptop or not ext:
        cprint("[yellow]No saved layout found. Run interactive setup first.[/yellow]")
        return False

    cprint(f"  → Applying saved layout: {layout} ({laptop} + {ext})")
    success = apply_xrandr_layout(layout, laptop, ext)
    if success:
        cprint("[green]  → Layout applied.[/green]")
    else:
        cprint("[red]  → Failed to apply layout.[/red]")
    return success


def main_menu() -> None:
    """Main interactive menu loop."""
    while True:
        print("\n")
        show_status_banner()
        cprint("\n  1. Run diagnosis & auto-fix")
        cprint("  2. Configure display layout")
        cprint("  3. Control brightness")
        cprint("  4. Fix suspend/resume issue")
        cprint("  5. iSight webcam setup guide")
        cprint("  6. Show system details")
        cprint("  7. Re-detect displays (xrandr --auto)")
        cprint("  8. Exit")

        try:
            choice = input("\nEnter choice [1-8]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "1":
            show_diagnosis_menu()
        elif choice == "2":
            configure_layout_interactive()
        elif choice == "3":
            brightness_menu()
        elif choice == "4":
            print_header("Suspend/Resume Fix")
            if SYSTEMD_SERVICE_PATH.exists():
                status_ok(f"Service already installed at {SYSTEMD_SERVICE_PATH}")
            else:
                cprint("\nThis will install a systemd service that runs 'xrandr --auto'")
                cprint("after the system wakes from suspend.")
                if confirm("Install suspend/resume service?"):
                    fix_suspend_resume_hook()
        elif choice == "5":
            show_isight_guide()
        elif choice == "6":
            show_system_details()
        elif choice == "7":
            print_header("Re-detecting Displays")
            fix_force_xrandr_detect()
        elif choice == "8":
            break
        else:
            cprint("[red]Invalid choice.[/red]")

        try:
            input("\nPress Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_diagnose_mode() -> None:
    """Non-interactive diagnosis mode (--diagnose)."""
    show_status_banner()
    print_header("Diagnosis")
    cprint("")

    # USB state
    usb = detect_apple_displays_usb()
    if usb:
        status_ok(f"Apple Cinema Display USB detected ({APPLE_CINEMA_USB_ID})")
    else:
        status_warn("Apple Cinema Display USB not detected")

    # xrandr state
    ext = get_external_outputs()
    edp_list = [o for o in detect_connected_outputs() if o["name"].startswith("eDP") and o["connected"]]
    if edp_list:
        status_ok(f"Laptop screen: {edp_list[0]['name']} (connected)")
    if ext:
        for o in ext:
            status_ok(f"External display: {o['name']} (connected, active)")
    else:
        all_ext = [o for o in detect_connected_outputs() if not o["name"].startswith("eDP")]
        if all_ext:
            status_warn(f"External outputs exist but disconnected: {', '.join(o['name'] for o in all_ext[:4])}")
        else:
            status_warn("No external display outputs detected")

    # System checks
    checks = [
        ("nvidia-drm.modeset=1 in /proc/cmdline", check_nvidia_modeset),
        ("appledisplay kernel module", check_appledisplay_module),
        ("udev brightness rule", check_udev_rules),
        ("suspend/resume hook", check_suspend_resume_hook),
    ]

    issues = []
    for label, check_fn in checks:
        issue = check_fn()
        if issue:
            issues.append(issue)
            if issue.severity == "error":
                status_fail(f"{label}  ← {issue.title}")
            else:
                status_warn(f"{label}  ← {issue.title}")
        else:
            status_ok(label)

    # Backlight
    bl = get_brightness()
    if bl:
        status_ok(f"Backlight control available: {bl['pct']}%")
    else:
        status_info("Backlight not available (appledisplay not loaded or USB not connected)")

    # Session
    ds = detect_display_server()
    if ds == "wayland":
        status_warn("Wayland session detected — xrandr layout features require X11")
    elif ds == "x11":
        status_ok("X11 session")
    else:
        status_info("Display server not detected")

    if issues:
        cprint(f"\n{len(issues)} issue(s) found.")
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            cprint(f"[red]{len(errors)} error(s) require attention.[/red]")
            cprint("\nRun with --fix to apply automatic fixes, or run interactively:")
            cprint("  python3 cinema_display_setup.py")
    else:
        cprint("\n[green]All checks passed.[/green]")


def parse_args() -> dict:
    """Minimal CLI argument parser (avoids click dependency)."""
    args = sys.argv[1:]
    result = {
        "diagnose": False,
        "fix": False,
        "brightness": None,
        "apply_layout": False,
        "help": False,
    }

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--diagnose", "-d"):
            result["diagnose"] = True
        elif a in ("--fix", "-f"):
            result["fix"] = True
        elif a in ("--apply-layout",):
            result["apply_layout"] = True
        elif a in ("--brightness", "-b"):
            i += 1
            if i < len(args):
                try:
                    result["brightness"] = int(args[i])
                except ValueError:
                    cprint(f"[red]--brightness requires an integer 0-100, got: {args[i]}[/red]")
                    sys.exit(1)
            else:
                cprint("[red]--brightness requires a value[/red]")
                sys.exit(1)
        elif a in ("--help", "-h"):
            result["help"] = True
        else:
            cprint(f"[red]Unknown argument: {a}[/red]")
            result["help"] = True
        i += 1

    return result


def print_help() -> None:
    cprint(textwrap.dedent("""
    cinema_display_setup.py — Apple Cinema Display setup tool for Ubuntu 24

    Usage:
      python3 cinema_display_setup.py [OPTIONS]

    Options:
      (no args)           Launch interactive menu
      --diagnose, -d      Run diagnosis and show issues (non-interactive)
      --fix, -f           Run diagnosis and apply all auto-fixes
      --brightness N, -b  Set brightness to N% (0-100)
      --apply-layout      Apply saved display layout from config
      --help, -h          Show this help

    Examples:
      python3 cinema_display_setup.py
      python3 cinema_display_setup.py --diagnose
      python3 cinema_display_setup.py --fix
      python3 cinema_display_setup.py --brightness 75
      python3 cinema_display_setup.py --apply-layout
    """))


def main() -> None:
    args = parse_args()

    if args["help"]:
        print_help()
        return

    if args["diagnose"] and not args["fix"] and args["brightness"] is None and not args["apply_layout"]:
        run_diagnose_mode()
        return

    if args["fix"]:
        show_status_banner()
        print_header("Auto-Fix Mode")
        issues = run_full_diagnosis()
        if not issues:
            cprint("[green]No issues found — nothing to fix.[/green]")
        else:
            reboot_needed = auto_fix_all(issues)
            if reboot_needed:
                cprint("\n[yellow]⚠  Reboot required for all changes to take effect.[/yellow]")
                cprint("Run: sudo reboot")
        return

    if args["brightness"] is not None:
        val = args["brightness"]
        cprint(f"Setting brightness to {val}%...")
        if set_brightness(val):
            bl = get_brightness()
            if bl:
                cprint(f"[green]Brightness set: {bl['pct']}%[/green]")
            else:
                cprint("[green]Brightness set.[/green]")
            save_config({"brightness": val})
        else:
            sys.exit(1)
        return

    if args["apply_layout"]:
        apply_saved_layout()
        return

    # Default: interactive menu
    main_menu()


if __name__ == "__main__":
    main()
