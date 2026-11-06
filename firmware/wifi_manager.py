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
SETUP_PORT = int(os.getenv("BEE_SETUP_PORT", "8080"))

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
        self._setup_lock = threading.Lock()

    @staticmethod
    def _load_known():
        if not KNOWN_WIFI_PATH.exists():
            return []
        try:
            # If the service user cannot read the file, try via sudo-cat.
            if os.access(KNOWN_WIFI_PATH, os.R_OK):
                raw = KNOWN_WIFI_PATH.read_text()
            else:
                res = _run(f"sudo cat {KNOWN_WIFI_PATH}")
                raw = res.stdout if res.returncode == 0 else "[]"
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"Failed to load known WiFi: {e}")
        return []

    def _save_known(self):
        """Persist known networks to JSON via sudo so the service user can write it."""
        tmp = Path("/tmp/known_wifi.json")
        tmp.write_text(json.dumps(self.known_networks, indent=2))
        _run(f"sudo mkdir -p {KNOWN_WIFI_PATH.parent}")
        _run(f"sudo cp {tmp} {KNOWN_WIFI_PATH}")
        _run(f"sudo chmod 644 {KNOWN_WIFI_PATH}")

    def apply_known_networks(self):
        """Regenerate wpa_supplicant.conf from known networks.

        If no known networks are configured yet, leave the existing
        wpa_supplicant.conf in place so the device keeps its current
        connection.
        """
        if not self.known_networks:
            print("No known networks configured; leaving existing wpa_supplicant.conf")
            return
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
        _run("sudo rfkill unblock wifi 2>/dev/null || true")
        # NetworkManager will fight hostapd for wlan0; disable it during setup.
        _run("sudo systemctl stop NetworkManager 2>/dev/null || true")
        _run("sudo systemctl stop dhcpcd 2>/dev/null || true")
        _run("sudo systemctl stop wpa_supplicant 2>/dev/null || true")
        _run("sudo pkill -9 wpa_supplicant 2>/dev/null || true")
        _run("sudo pkill -9 dhcpcd 2>/dev/null || true")
        _run("sudo ip link set wlan0 down")
        time.sleep(0.5)
        _run("sudo ip addr flush dev wlan0")
        _run(f"sudo ip addr add {SETUP_IP}/24 dev wlan0")
        _run("sudo ip link set wlan0 up")
        time.sleep(0.5)

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
        with self._setup_lock:
            if self._setup_running.is_set():
                print("Setup mode already running")
                return
            self._setup_running.set()
        self.setup_mode = True
        try:
            self._configure_ap()
        except Exception as e:
            print(f"AP configuration failed: {e}")
            self._setup_running.clear()
            raise
        self._setup_thread = threading.Thread(
            target=app.run,
            kwargs={"host": SETUP_IP, "port": SETUP_PORT, "debug": False, "use_reloader": False},
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
    if _wifi_manager.known_networks:
        known_html = "".join(f"<li>{n['ssid']}</li>" for n in _wifi_manager.known_networks)
    else:
        known_html = "<li style='color:#71717a;list-style:none;margin-left:-1.25rem;'>No saved networks yet</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bee Wi-Fi Setup</title>
<style>
  :root {{
    --bg: #0f0f10;
    --card: #18181b;
    --text: #f4f4f5;
    --muted: #a1a1aa;
    --accent: #fbbf24;
    --accent-dark: #d97706;
    --border: #27272a;
    --input: #27272a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    display: flex;
    justify-content: center;
    padding: 2rem 1rem;
    min-height: 100vh;
  }}
  .card {{
    width: 100%;
    max-width: 420px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 1.25rem;
    padding: 1.75rem;
    box-shadow: 0 20px 40px rgba(0,0,0,0.35);
  }}
  .logo {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
  }}
  .logo-icon {{
    width: 2.5rem;
    height: 2.5rem;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-dark) 100%);
    border-radius: 0.75rem;
    display: grid;
    place-items: center;
    font-size: 1.4rem;
  }}
  h1 {{
    font-size: 1.35rem;
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.02em;
  }}
  .tagline {{
    color: var(--muted);
    font-size: 0.9rem;
    margin-bottom: 1.5rem;
  }}
  label {{
    display: block;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 1rem 0 0.4rem;
  }}
  input {{
    width: 100%;
    padding: 0.85rem 1rem;
    background: var(--input);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    color: var(--text);
    font-size: 1rem;
    outline: none;
    transition: border-color 0.15s;
  }}
  input:focus {{
    border-color: var(--accent);
  }}
  .optional {{
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
    color: #71717a;
  }}
  button {{
    width: 100%;
    margin-top: 1.5rem;
    padding: 0.95rem;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-dark) 100%);
    color: #1a1a1a;
    border: none;
    border-radius: 0.75rem;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    transition: transform 0.1s, box-shadow 0.15s;
  }}
  button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(251, 191, 36, 0.25);
  }}
  .known {{
    margin-top: 1.75rem;
    padding-top: 1.25rem;
    border-top: 1px solid var(--border);
  }}
  .known h3 {{
    margin: 0 0 0.75rem;
    font-size: 0.9rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .known ul {{
    margin: 0;
    padding-left: 1.25rem;
    color: var(--text);
  }}
  .known li {{
    margin: 0.35rem 0;
    font-size: 0.95rem;
  }}
  .status {{
    margin-top: 1rem;
    padding: 0.85rem 1rem;
    background: rgba(251, 191, 36, 0.1);
    border-left: 3px solid var(--accent);
    border-radius: 0 0.5rem 0.5rem 0;
    color: var(--text);
    font-size: 0.9rem;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="logo">
      <div class="logo-icon">🐝</div>
      <div>
        <h1>Bee Wi-Fi Setup</h1>
        <div class="tagline">Connect your wearable to the world</div>
      </div>
    </div>
    <div class="status">
      You are connected to <strong>bee-config</strong>. Fill in your home network details below and the Bee will restart automatically.
    </div>
    <form method="post" action="/connect">
      <label for="ssid">Wi-Fi Network</label>
      <input id="ssid" name="ssid" required placeholder="e.g. HomeNetwork">

      <label for="psk">Passphrase</label>
      <input id="psk" name="psk" type="password" required placeholder="Your Wi-Fi password">

      <label for="backend_url" class="optional">Backend URL <span style="color:#71717a">(optional)</span></label>
      <input id="backend_url" name="backend_url" placeholder="https://bee-api.singhdns.co.uk">

      <label for="api_key" class="optional">API Key <span style="color:#71717a">(optional)</span></label>
      <input id="api_key" name="api_key" placeholder="bee_...">

      <button type="submit">Connect &amp; Save</button>
    </form>
    <div class="known">
      <h3>Saved Networks</h3>
      <ul>{known_html}</ul>
    </div>
  </div>
</body>
</html>"""


result_page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bee Wi-Fi Setup</title>
<style>
  :root {{ --bg:#0f0f10; --card:#18181b; --text:#f4f4f5; --muted:#a1a1aa; --accent:#fbbf24; --accent-dark:#d97706; --border:#27272a; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; display:flex; justify-content:center; align-items:center; min-height:100vh; padding:1rem; }}
  .card {{ width:100%; max-width:420px; background:var(--card); border:1px solid var(--border); border-radius:1.25rem; padding:2rem; text-align:center; box-shadow:0 20px 40px rgba(0,0,0,0.35); }}
  .icon {{ width:4rem; height:4rem; background:linear-gradient(135deg,var(--accent) 0%,var(--accent-dark) 100%); border-radius:50%; display:grid; place-items:center; margin:0 auto 1.25rem; font-size:2rem; }}
  h1 {{ font-size:1.35rem; margin:0 0 0.5rem; }}
  p {{ color:var(--muted); margin:0 0 1.5rem; line-height:1.5; }}
  a {{ display:inline-block; padding:0.75rem 1.25rem; background:var(--border); color:var(--text); text-decoration:none; border-radius:0.75rem; font-weight:600; }}
  a:hover {{ background:#3f3f46; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    <p>{message}</p>
    {back_link}
  </div>
</body>
</html>"""


@app.route("/connect", methods=["POST"])
def connect():
    try:
        ssid = request.form.get("ssid", "").strip()
        psk = request.form.get("psk", "").strip()
        backend_url = request.form.get("backend_url", "").strip()
        api_key = request.form.get("api_key", "").strip()
        if not ssid or not psk:
            return "SSID and passphrase required", 400

        ok = _wifi_manager.add_network(ssid, psk)

        # Update device env if provided (write as service user then sudo mv)
        env_path = Path("/opt/bee-device/.env")
        if env_path.exists() and (backend_url or api_key):
            try:
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
                tmp_env = Path("/tmp/bee-device.env")
                tmp_env.write_text("\n".join(new_lines) + "\n")
                _run(f"sudo cp {tmp_env} {env_path}")
                _run(f"sudo chmod 644 {env_path}")
            except Exception as e:
                print(f"Env update failed (ignored): {e}")

        # Always reboot after saving; the device cannot test the network while it is the AP.
        threading.Thread(target=_reconnect, daemon=True).start()
        if ok:
            return result_page.format(icon="✅", title="Saved & connected", message="The Bee will restart and join your Wi-Fi. You can close this page.", back_link="")
        return result_page.format(icon="💾", title="Network saved", message="The Bee will reboot and try to join the network. If it fails, triple-click the button to re-enter setup.", back_link='<a href="/">Back</a>')
    except Exception as e:
        import traceback
        print(f"/connect error: {e}\n{traceback.format_exc()}")
        return f"<h2>Server Error</h2><pre>{e}</pre><p><a href='/'>Back</a></p>", 500


def _reconnect():
    """Leave setup mode and restart the device service to apply new network/env."""
    try:
        _wifi_manager.leave_setup_mode()
    except Exception as e:
        print(f"leave_setup_mode failed: {e}")
    os.system("sudo systemctl restart bee-device")


def create_manager():
    global _wifi_manager
    _wifi_manager = WiFiManager()
    return _wifi_manager


if __name__ == "__main__":
    mgr = create_manager()
    mgr.run_setup_then_connect()
    while True:
        time.sleep(1)
