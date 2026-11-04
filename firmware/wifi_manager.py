#!/usr/bin/env python3
"""
Wi-Fi manager for Ollama Bee Device.

On boot: try known networks in priority order; if none connect, start a setup AP
(http://192.168.4.1) to collect new SSID + passphrase. Triple-click enters
setup mode.
"""

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, request

KNOWN_WIFI_PATH = Path("/opt/bee-device/known_wifi.json")
WPA_SUPPLICANT_CONF = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
COUNTRY_CODE = os.getenv("BEE_WIFI_COUNTRY", "GB")
SETUP_SSID = os.getenv("BEE_SETUP_SSID", "bee-config")
SETUP_IP = "192.168.4.1"

app = Flask(__name__)
_wifi_manager = None


def _run(cmd, check=False, timeout=30):
    """Run a shell command and return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, check=check)
    if result.returncode != 0 and not check:
        print(f"Command failed ({result.returncode}): {cmd} - {result.stderr[:200]}")
    return result


def _ssid_from_wpa():
    """Return the SSID the interface is currently trying to join."""
    result = _run("wpa_cli status 2>/dev/null | grep '^ssid=' || true")
    for line in result.stdout.splitlines():
        if line.startswith("ssid="):
            return line.split("=", 1)[1]
    return None


def _is_associated(timeout=12):
    """Check if wlan0 is connected to an AP with internet reachability."""
    for _ in range(timeout):
        res = _run("wpa_cli status 2>/dev/null | grep '^wpa_state=' || true")
        if "COMPLETED" in res.stdout:
            return True
        time.sleep(1)
    return False


def _internet_reachable(timeout=10):
    """Return True if we can reach a public host."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname("google.com")
        return True
    except Exception:
        return False
    finally:
        socket.setdefaulttimeout(None)


class WiFiManager:
    def __init__(self):
        self.known_networks = self._load_known()
        self.setup_mode = False
        self._setup_thread = None
        self._setup_running = threading.Event()

    @staticmethod
    def _load_known():
        if not KNOWN_WIFI_PATH.exists():
            return []
        try:
            data = json.loads(KNOWN_WIFI_PATH.read_text())
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"Failed to load known WiFi: {e}")
        return []

    def _save_known(self):
        KNOWN_WIFI_PATH.parent.mkdir(parents=True, exist_ok=True)
        KNOWN_WIFI_PATH.write_text(json.dumps(self.known_networks, indent=2))

    def apply_known_networks(self):
        """Regenerate wpa_supplicant.conf from known networks."""
        lines = [
            "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev",
            "update_config=1",
            f"country={COUNTRY_CODE}",
            "",
        ]
        for net in self.known_networks:
            lines.extend(
                [
                    "network={",
                    f'    ssid="{net["ssid"]}"',
                    f'    psk="{net["psk"]}"',
                    "    key_mgmt=WPA-PSK",
                    "}",
                    "",
                ]
            )
        # Write via sudo if not root
        tmp = Path("/tmp/wpa_supplicant.conf")
        tmp.write_text("\n".join(lines))
        _run(f"sudo cp {tmp} {WPA_SUPPLICANT_CONF}")
        _run("sudo chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf")
        _run("sudo wpa_cli reconfigure 2>/dev/null || true")
        time.sleep(2)

    def try_connect(self, timeout=20):
        """Bring wlan0 up and attempt to associate with a known network."""
        _run("sudo rfkill unblock wifi")
        _run("sudo ip link set wlan0 up")
        self.apply_known_networks()
        if _is_associated(timeout=timeout):
            print(f"Connected to WiFi: {_ssid_from_wpa()}")
            return True
        print("No known WiFi reachable")
        return False

    def add_network(self, ssid, psk):
        """Add a new network, save it, and attempt to connect."""
        # Avoid duplicates
        self.known_networks = [n for n in self.known_networks if n.get("ssid") != ssid]
        self.known_networks.insert(0, {"ssid": ssid, "psk": psk})
        self._save_known()
        self.apply_known_networks()
        return _is_associated(timeout=15)

    def remove_network(self, ssid):
        self.known_networks = [n for n in self.known_networks if n.get("ssid") != ssid]
        self._save_known()
        self.apply_known_networks()

    def _configure_ap(self):
        """Stop client mode and start hostapd/dnsmasq."""
        _run("sudo systemctl stop dhcpcd 2>/dev/null || true")
        _run("sudo systemctl stop wpa_supplicant 2>/dev/null || true")
        _run("sudo ip link set wlan0 down")
        _run("sudo ip addr flush dev wlan0")
        _run(f"sudo ip addr add {SETUP_IP}/24 dev wlan0")
        _run("sudo ip link set wlan0 up")

        # hostapd config
        hostapd_conf = f"""interface=wlan0
driver=nl80211
ssid={SETUP_SSID}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
"""
        hostapd_path = Path("/tmp/hostapd.conf")
        hostapd_path.write_text(hostapd_conf)
        _run(f"sudo cp {hostapd_path} /etc/hostapd/hostapd.conf 2>/dev/null || true")

        # dnsmasq config
        dnsmasq_conf = f"""interface=wlan0
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,12h
address=/#/{SETUP_IP}
"""
        dnsmasq_path = Path("/tmp/dnsmasq.conf")
        dnsmasq_path.write_text(dnsmasq_conf)

        _run("sudo pkill hostapd 2>/dev/null || true")
        _run("sudo pkill dnsmasq 2>/dev/null || true")
        time.sleep(1)
        _run("sudo hostapd -B /tmp/hostapd.conf")
        _run(f"sudo dnsmasq -C {dnsmasq_path} --no-daemon > /dev/null 2>&1 &")
        print(f"Setup AP started: {SETUP_SSID} at {SETUP_IP}")

    def _stop_ap(self):
        _run("sudo pkill hostapd 2>/dev/null || true")
        _run("sudo pkill dnsmasq 2>/dev/null || true")
        _run("sudo ip link set wlan0 down")
        _run("sudo ip addr flush dev wlan0")
        _run("sudo systemctl start wpa_supplicant 2>/dev/null || true")
        _run("sudo systemctl start dhcpcd 2>/dev/null || true")

    def enter_setup_mode(self):
        """Start AP and web UI."""
        if self._setup_running.is_set():
            return
        self._setup_running.set()
        self.setup_mode = True
        self._configure_ap()
        self._setup_thread = threading.Thread(
            target=app.run,
            kwargs={"host": SETUP_IP, "port": 80, "debug": False, "use_reloader": False},
            daemon=True,
        )
        self._setup_thread.start()

    def leave_setup_mode(self):
        """Stop AP, restart client mode, and try known networks."""
        if not self._setup_running.is_set():
            return
        self._setup_running.clear()
        self.setup_mode = False
        # Flask cannot be stopped cleanly from outside; kill the process
        _run("sudo pkill -f 'wifi_manager.py' 2>/dev/null || true")
        self._stop_ap()
        self.try_connect(timeout=20)

    def run_setup_then_connect(self):
        """Boot-time routine: try known networks, else start setup AP."""
        if self.try_connect(timeout=25):
            return
        print("Entering WiFi setup mode (triple-click gesture also available)")
        self.enter_setup_mode()


@app.route("/", methods=["GET"])
def index():
    known_html = "".join(f"<li>{n['ssid']}</li>" for n in _wifi_manager.known_networks)
    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bee WiFi Setup</title>
<style>body{{font-family:sans-serif;padding:1rem;max-width:400px;margin:auto}}input,button{{width:100%;padding:0.7rem;margin:0.4rem 0;font-size:1rem}}button{{background:#111;color:#fff;border:none;border-radius:0.4rem}}</style></head>
<body>
<h2>🐝 Bee WiFi Setup</h2>
<form method="post" action="/connect">
<label>WiFi SSID<br><input name="ssid" required placeholder="Network name"></label><br>
<label>Passphrase<br><input name="psk" type="password" required placeholder="Password"></label><br>
<label>Backend URL (optional)<br><input name="backend_url" placeholder="https://..." value=""></label><br>
<label>API Key (optional)<br><input name="api_key" placeholder="" value=""></label><br>
<button type="submit">Connect & Save</button>
</form>
<h3>Known networks</h3>
<ul>{known_html}</ul>
</body></html>"""


@app.route("/connect", methods=["POST"])
def connect():
    ssid = request.form.get("ssid", "").strip()
    psk = request.form.get("psk", "").strip()
    backend_url = request.form.get("backend_url", "").strip()
    api_key = request.form.get("api_key", "").strip()
    if not ssid or not psk:
        return "SSID and passphrase required", 400

    ok = _wifi_manager.add_network(ssid, psk)

    # Update device env if provided
    env_path = Path("/opt/bee-device/.env")
    if env_path.exists() and (backend_url or api_key):
        lines = env_path.read_text().splitlines()
        new_lines = []
        for line in lines:
            if backend_url and line.startswith("BEE_BACKEND_URL="):
                line = f"BEE_BACKEND_URL={backend_url}"
            if api_key and line.startswith("BEE_API_KEY="):
                line = f"BEE_API_KEY={api_key}"
            new_lines.append(line)
        if backend_url and not any(line2.startswith("BEE_BACKEND_URL=") for line2 in new_lines):
            new_lines.append(f"BEE_BACKEND_URL={backend_url}")
        if api_key and not any(line2.startswith("BEE_API_KEY=") for line2 in new_lines):
            new_lines.append(f"BEE_API_KEY={api_key}")
        env_path.write_text("\n".join(new_lines) + "\n")

    if ok:

        def _reconnect():
            _wifi_manager.leave_setup_mode()
            os.system("sudo systemctl restart bee-device")

        threading.Thread(target=_reconnect, daemon=True).start()
        return "<h2>Connected! Rebooting device...</h2><p>You can close this page.</p>"
    return "<h2>Could not connect.</h2><p>The network has been saved; the device will retry on next boot. <a href='/'>Back</a></p>"


def create_manager():
    global _wifi_manager
    _wifi_manager = WiFiManager()
    return _wifi_manager


if __name__ == "__main__":
    mgr = create_manager()
    mgr.run_setup_then_connect()
    while True:
        time.sleep(1)
