# IoT-Enabled Waste Monitoring and Characterization System

An IoT system that **weighs** an item placed on a load-cell scale, **identifies** it with computer vision, **categorizes** it (plastic, paper, metal, glass, organic, residual), **stores** the event locally, and shows it in a **real-time web dashboard** with analytics — all running on a Raspberry Pi.

## Hardware

| Component | Notes |
|---|---|
| Raspberry Pi (3/4/5) | Runs the whole stack. |
| NAU7802 24-bit ADC | Connected over I²C (SDA/SCL). |
| 4 × Load cell | Wired together as a single Wheatstone bridge to the NAU7802 (E+, E-, A+, A-). |
| USB camera | Plugged into any USB port. |

Enable I²C on the Pi with `sudo raspi-config` → *Interface Options* → *I2C*.

## Architecture

```
┌──────────┐   ┌──────────┐   ┌────────────┐
│ NAU7802  │──▶│          │   │  USB Cam   │
│ + 4 LCs  │   │ Raspberry│◀──│            │
└──────────┘   │   Pi     │   └────────────┘
               │          │
               │ Python   │──▶ SQLite ──▶ Flask + SocketIO ──▶ Browser dashboard
               │ services │
               └──────────┘
```

A single Python process runs:
1. A background thread sampling the scale at ~10 Hz.
2. A stable-event detector that fires only when weight is above a threshold **and** stable for a configurable window (so it ignores oscillation and adjustments).
3. On each event: capture a USB-camera frame → run a TFLite object detector → map the label to a waste category → save the image → insert a row in SQLite → push a Socket.IO message.
4. A Flask + Flask-SocketIO web server with a live dashboard and analytics page.

## Project Layout

```
.
├── run.py                       # entrypoint
├── config.example.yaml          # copy to config.yaml and edit
├── requirements.txt             # base deps (work on any OS)
├── requirements-pi.txt          # Pi-only deps (NAU7802, tflite_runtime)
├── app/
│   ├── config.py                # YAML config loader
│   ├── hardware/                # Scale + Camera (real + mock)
│   ├── ai/                      # Detector interface, TFLite impl, label maps
│   ├── core/                    # Pipeline, DB models, dataclasses
│   ├── web/                     # Flask app, routes, templates, static
│   └── utils/                   # logging
├── scripts/
│   ├── calibrate_scale.py       # interactive tare + calibration
│   └── download_model.py        # fetches EfficientDet-Lite0 TFLite model
├── tests/                       # pytest suite (uses mock hardware)
└── data/                        # SQLite db + captured images (gitignored)
```

## Quick Start (laptop, mock hardware)

You don't need a Pi to develop the dashboard — the system ships with a mock scale + mock camera + mock detector.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml          # already has use_mock: true
python run.py
```

Open <http://localhost:5000>. The mock scale will simulate items being placed and removed every few seconds; the dashboard will update live.

## Running on the Raspberry Pi

```bash
# System packages for OpenCV + I2C
sudo apt update
sudo apt install -y python3-pip python3-venv python3-opencv i2c-tools libatlas-base-dev

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-pi.txt

# Download a small TFLite object detector (EfficientDet-Lite0 + COCO labels)
python -m scripts.download_model

cp config.example.yaml config.yaml
# Edit config.yaml: set hardware.use_mock: false and ai.backend: tflite
```

### Calibrate the scale

```bash
python -m scripts.calibrate_scale --known-weight 500
```

Follow the prompts (clear the platform, then place a known weight). Copy the printed `tare_offset` and `calibration_factor` into `config.yaml` under `hardware.scale`.

### Start the system

```bash
python run.py
```

The web UI is at `http://<pi-ip>:5000`.

### Auto-start on boot (systemd)

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

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now waste-monitor
```

## Configuration reference

All settings live in `config.yaml` (see `config.example.yaml` for the full annotated template). Key sections:

* `hardware.use_mock` — `true` for development, `false` to use the real NAU7802 + USB camera.
* `hardware.scale.calibration_factor` / `tare_offset` — produced by `calibrate_scale.py`.
* `events` — threshold, stability window, and reset hysteresis for the placement-detector state machine.
* `ai.backend` — `mock` or `tflite`. With `tflite`, set `model_path` and `labels_path`.
* `database.url` — SQLAlchemy URL, defaults to local SQLite.
* `web.host`/`port` — where the Flask server binds.

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
| Socket.IO `weight` | Live weight stream |
| Socket.IO `new_event` | Pushed when a new placement is recorded |

## Tests

```bash
pip install -r requirements.txt
pytest -v
```

The test suite uses the mock scale, mock camera, and mock detector, so it runs anywhere — no hardware required.

## Extending

* **Custom waste classifier:** swap the TFLite model and label-to-category map in `app/ai/labels.py` for a waste-specific classifier (e.g., TrashNet).
* **Different categories:** edit `DEFAULT_CATEGORIES` in `app/core/db.py` (the dashboard reads them dynamically).
* **Different DB:** point `database.url` at Postgres/MySQL — the SQLAlchemy layer handles it.
