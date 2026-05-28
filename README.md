# IoT-Enabled Waste Monitoring and Characterization System

An IoT system that **weighs** an item placed on a load-cell scale, **identifies** it with computer vision, **categorizes** it (plastic, paper, metal, glass, organic, residual), **stores** the event locally, and shows it in a **real-time web dashboard** with analytics — all running on a Raspberry Pi.

## Hardware

| Component | Notes |
|---|---|
| Raspberry Pi (3/4/5) | Runs the whole stack. |
| ADS1115 16-bit ADC | Connected over I²C (SDA/SCL). Reads the sensor voltage on **channel 1 (AIN1)**. |
| Analogue weight sensor / load-cell amplifier | Voltage output wired to AIN1. Must output 0–5 V. |
| BSS138 bidirectional I²C level shifter | Translates 3.3 V Pi I²C ↔ 5 V ADS1115 logic. |
| USB camera | Plugged into any USB port. |

Enable I²C on the Pi — see [step 1a below](#1a--enable-i2c).

## Wiring

The ADS1115 is powered at **5 V** so it can safely read the full 0–5 V sensor range (PGA set to ±6.144 V). A bidirectional level shifter on the I²C lines protects the Pi's 3.3 V GPIO.

```
Raspberry Pi              Level Shifter (BSS138)       ADS1115
────────────────          ──────────────────────       ───────────────────
3.3V  (Pin 1)  ─────────► LV (3.3V ref)
5V    (Pin 2)  ─────────► HV (5V ref)  ────────────► VDD
GND   (Pin 6)  ─────────► GND ──────────────────────► GND
                                                       ADDR ──► GND  (addr 0x48)

SDA   (Pin 3)  ─────────► LV1 ◄──────► HV1 ─────────► SDA
SCL   (Pin 5)  ─────────► LV2 ◄──────► HV2 ─────────► SCL

                                         Sensor output ──► AIN1  (channel 1)
                                         Sensor GND    ──► GND
```

> **Note:** Do **not** connect the ADS1115 VDD directly to the Pi's 3.3 V pin when reading 5 V signals — the analog input must not exceed VDD + 0.3 V.

## Architecture

```
┌───────────────┐   ┌──────────────┐   ┌────────────┐
│   ADS1115     │──▶│              │   │  USB Cam   │
│  (AIN1, 5V)  │   │  Raspberry   │◀──│            │
└───────────────┘   │     Pi       │   └────────────┘
                    │              │
                    │   Python     │──▶ SQLite ──▶ Flask + SocketIO ──▶ Browser dashboard
                    │   services   │
                    └──────────────┘
```

A single Python process runs:
1. A background thread sampling the ADS1115 channel 1 voltage at ~10 Hz.
2. A stable-event detector that fires only when the derived weight is above a threshold **and** stable for a configurable window (ignores oscillation and adjustments).
3. On each event: capture a USB-camera frame → run a TFLite object detector → map the label to a waste category → save the image → insert a row in SQLite → push a Socket.IO message.
4. A Flask + Flask-SocketIO web server with a live dashboard and analytics page.

## Project Layout

```
.
├── run.py                       # entrypoint
├── config.example.yaml          # copy to config.yaml and edit
├── requirements.txt             # base deps (work on any OS)
├── requirements-pi.txt          # Pi-only deps (ADS1115, tflite_runtime)
├── app/
│   ├── config.py                # YAML config loader
│   ├── hardware/                # Scale + Camera (real + mock)
│   ├── ai/                      # Detector interface, TFLite impl, label maps
│   ├── core/                    # Pipeline, DB models, dataclasses
│   ├── web/                     # Flask app, routes, templates, static
│   └── utils/                   # logging
├── scripts/
│   ├── calibrate_scale.py       # interactive tare + calibration (voltage-based)
│   └── download_model.py        # fetches EfficientDet-Lite0 TFLite model
├── tests/                       # pytest suite (uses mock hardware)
└── data/                        # SQLite db + captured images (gitignored)
```

---

## Quick Start (laptop / mock hardware)

You don't need a Pi to develop the dashboard — the system ships with a mock scale, mock camera, and mock detector.

### Windows

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml   # already has use_mock: true
python run.py
```

### macOS / Linux

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml          # already has use_mock: true
python run.py
```

Open <http://localhost:5000>. The mock scale simulates items being placed and removed every few seconds; the dashboard updates live.

---

## Running on the Raspberry Pi

### 1 — System packages

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-opencv i2c-tools libopenblas-dev
```

### 1a — Enable I²C

**Option A — raspi-config (easiest)**

```bash
sudo raspi-config
```

Navigate to *Interface Options* → *I2C* → *Yes* → *Finish*, then reboot:

```bash
sudo reboot
```

**Option B — manual (Trixie / Bookworm)**

On Raspberry Pi OS Trixie and Bookworm the boot config is at `/boot/firmware/config.txt` (not `/boot/config.txt`):

```bash
# Add the I2C overlay if it is not already present
grep -q 'dtparam=i2c_arm=on' /boot/firmware/config.txt \
  || echo 'dtparam=i2c_arm=on' | sudo tee -a /boot/firmware/config.txt

# Make sure the i2c-dev module loads at boot
grep -q 'i2c-dev' /etc/modules \
  || echo 'i2c-dev' | sudo tee -a /etc/modules

sudo reboot
```

After the reboot, confirm the device node exists:

```bash
ls /dev/i2c*   # should show /dev/i2c-1
```

> **Note:** `libatlas-base-dev` was removed from Raspberry Pi OS Bookworm (Debian 12) and is not present in Trixie (Debian 13) either. Use `libopenblas-dev` instead — it provides the same BLAS/LAPACK functionality required by NumPy and SciPy on ARM.

### 2 — Verify the ADS1115 is detected on I²C

```bash
i2cdetect -y 1
# You should see 0x48 in the output
```

> If you get `Could not open file '/dev/i2c-1'`, I²C is not enabled yet — go back to **step 1a**.

### 3 — Python environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-pi.txt
```

### 4 — Download the TFLite model

```bash
python -m scripts.download_model
```

### 5 — Configure

```bash
cp config.example.yaml config.yaml
```

Open `config.yaml` and set:

```yaml
hardware:
  use_mock: false          # use real ADS1115 + USB camera
  scale:
    i2c_address: 0x48      # ADS1115 default (ADDR pin → GND)
    gain: 0.6667           # 2/3 = ±6.144V PGA, covers full 0–5V range
    tare_offset: 0.0       # filled in by calibrate_scale.py
    calibration_factor: 1.0  # filled in by calibrate_scale.py

ai:
  backend: tflite
```

### 6 — Calibrate the scale

```bash
python -m scripts.calibrate_scale --known-weight 500
```

Follow the prompts:
1. Clear the platform → press Enter (captures tare voltage).
2. Place the known weight → press Enter (computes V/g calibration factor).

Copy the printed `tare_offset` and `calibration_factor` values into `config.yaml` under `hardware.scale`.

### 7 — Start the system

```bash
python run.py
```

Open `http://<pi-ip>:5000` in a browser on the same network.

---

## Static IP & Local Network Access

The Flask server already binds to `0.0.0.0`, so every device on your Wi-Fi/LAN can reach it.  
Setting a **static IP** on the Pi gives it a predictable address you can bookmark like a website.

### Find your current network details first

```bash
ip route show default   # note: gateway IP and interface name (e.g. eth0 or wlan0)
ip addr show wlan0      # note: current IP and prefix length (e.g. 192.168.1.x/24)
```

---

### Raspberry Pi OS **Trixie** (Debian 13), **Bookworm** (Debian 12) — NetworkManager / `nmcli`

```bash
# List connection names
nmcli connection show

# Apply a static IP (replace values to match your network)
sudo nmcli connection modify "preconfigured" \
  ipv4.method manual \
  ipv4.addresses 192.168.1.100/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.dns "8.8.8.8 8.8.4.4"

sudo nmcli connection up "preconfigured"
```

> Replace `"preconfigured"` with your actual connection name shown by `nmcli connection show`.  
> Replace `192.168.1.100` with the address you want, and `192.168.1.1` with your router's IP.

---

### Raspberry Pi OS **Bullseye** (Debian 11) and older — `dhcpcd`

Add the following block to the **bottom** of `/etc/dhcpcd.conf`:

```
interface wlan0          # use eth0 for wired ethernet
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=8.8.8.8 8.8.4.4
```

Apply:

```bash
sudo systemctl restart dhcpcd
```

---

### Access the dashboard

Once the static IP is set, open this in any browser on the same network:

```
http://192.168.1.100:5000
```

---

### Optional — remove the port number (access like a plain website)

Port 80 is the default HTTP port, so browsers don't require you to type `:5000`.  
Non-root processes cannot bind port 80 directly; use `authbind`:

```bash
sudo apt install -y authbind
sudo touch /etc/authbind/byport/80
sudo chown pi /etc/authbind/byport/80
sudo chmod 755 /etc/authbind/byport/80
```

Edit `config.yaml`:

```yaml
web:
  host: 0.0.0.0
  port: 80
```

Start the app through `authbind`:

```bash
authbind --deep python run.py
```

Or update the systemd `ExecStart` line (see [Auto-start on boot](#auto-start-on-boot-systemd)):

```ini
ExecStart=authbind --deep /home/pi/IoT-Waste-Monitor/.venv/bin/python run.py
```

Now the dashboard is reachable at just:

```
http://192.168.1.100
```

---

## Auto-start on boot (systemd)

Create `/etc/systemd/system/waste-monitor.service`:

```ini
[Unit]
Description=IoT Waste Monitor
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/IoT-Waste-Monitor
ExecStart=/home/pi/IoT-Waste-Monitor/.venv/bin/python run.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now waste-monitor
sudo systemctl status waste-monitor   # confirm it is running
```

View live logs:

```bash
journalctl -u waste-monitor -f
```

---

## Configuration Reference

All settings live in `config.yaml` (see `config.example.yaml` for the full annotated template).

| Key | Default | Description |
|---|---|---|
| `hardware.use_mock` | `true` | `false` to use real ADS1115 + USB camera |
| `hardware.scale.i2c_address` | `0x48` | ADS1115 I²C address (ADDR pin → GND) |
| `hardware.scale.gain` | `0.6667` | ADS1115 PGA: `0.6667`=±6.144 V, `1`=±4.096 V, `2`=±2.048 V |
| `hardware.scale.tare_offset` | `0.0` | Sensor voltage (V) at zero weight — set by `calibrate_scale.py` |
| `hardware.scale.calibration_factor` | `1.0` | Volts per gram (V/g) — set by `calibrate_scale.py` |
| `hardware.scale.sample_rate_hz` | `10` | Target polling rate |
| `events.min_weight_g` | `5.0` | Minimum weight (g) to start a placement event |
| `events.stability_window` | `8` | Samples that must be within `stability_g` stddev |
| `events.stability_g` | `1.0` | Max stddev (g) to declare a stable reading |
| `events.reset_threshold_g` | `2.0` | Weight must drop below this to reset after an event |
| `ai.backend` | `mock` | `mock` or `tflite` |
| `ai.model_path` | — | Path to `.tflite` model file |
| `database.url` | SQLite | SQLAlchemy URL |
| `web.host` / `web.port` | `0.0.0.0:5000` | Flask bind address |

---

## Web API

| Route | Description |
|---|---|
| `GET /` | Live dashboard with current weight + latest item |
| `GET /analytics` | Charts (per-category weight/counts, daily totals) |
| `GET /api/events?limit=&offset=&category=&since=&until=` | List events (JSON) |
| `GET /api/summary?window=all\|today\|week` | Aggregate stats |
| `GET /api/daily?days=N` | Daily totals for the last N days |
| `GET /api/categories` | Category list |
| `GET /api/events.csv` | Export all events as CSV |
| `GET /images/<event_id>` | Captured image for an event |
| Socket.IO `weight` | Live weight stream (~10 Hz) |
| Socket.IO `new_event` | Pushed when a new placement is recorded |

---

## Tests

```bash
pip install -r requirements.txt
pytest -v
```

The test suite uses the mock scale, mock camera, and mock detector — no hardware required.

---

## Extending

* **Custom waste classifier:** swap the TFLite model and label-to-category map in `app/ai/labels.py` for a waste-specific classifier (e.g., TrashNet).
* **Different categories:** edit `DEFAULT_CATEGORIES` in `app/core/db.py` (the dashboard reads them dynamically).
* **Different DB:** point `database.url` at Postgres/MySQL — the SQLAlchemy layer handles it.
* **Different ADC channel:** change `ADS.P1` in `app/hardware/scale.py` to `ADS.P0`, `ADS.P2`, or `ADS.P3` to read from a different ADS1115 channel.
