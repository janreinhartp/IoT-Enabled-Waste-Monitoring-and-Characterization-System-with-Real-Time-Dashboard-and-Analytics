# IoT-Enabled Waste Monitoring and Characterization System

An IoT system that **weighs** an item placed on a load-cell scale, **identifies** it with computer vision, **categorizes** it (plastic, paper, metal, glass, organic), **stores** the event locally, and shows it in a **real-time web dashboard** with analytics — all running on a Raspberry Pi.

## Hardware

| Component | Qty | Notes |
|---|---|---|
| Raspberry Pi (3/4/5) | 1 | Runs the whole stack. Connected to the router via Ethernet. |
| Load cells | 4 | Wired to the junction box to form a single Wheatstone bridge. |
| Load cell junction box | 1 | Combines the 4 load cells into E+/E−/S+/S− outputs. |
| RS485 Modbus RTU weight indicator module | 1 | Powered by 10–28 V DC. Reads the load cell bridge directly. Communicates over RS485 Modbus RTU at 9600 baud. |
| Feiyang TTL-to-RS485 module *(option A)* | 1 | Converts Pi 3.3 V UART (TXD/RXD) to RS485 differential pair (A+/B−). Auto direction control — no DE/RE pin needed. |
| **— OR —** | | |
| Waveshare RS485 TO ETH (B) *(option B)* | 1 | Bridges the RS485 bus to Ethernet in Modbus TCP↔RTU gateway mode. Powered by 9–24 V DC. No UART wiring to the Pi required — communicates over the LAN. |
| I2C LCD display (HD44780) | 1 | 16×2 or 20×4 character LCD with PCF8574 I2C backpack. Displays live weight + AI detection. |
| Push button × 2 | 2 | **Analyze** (GPIO 17) and **Record** (GPIO 27). Normally-open, wired to GND. Internal pull-up enabled via RPi.GPIO. |
| Buck converter (12 V → 5 V) | 1 | Steps down the 12 V supply to 5 V for the Pi. |
| 12 V DC power supply (≥ 3 A) | 1 | Powers the weight indicator module directly, and the buck converter. |
| USB camera | 1 | Plugged into any Pi USB port. |
| Router | 1 | Pi connects via Ethernet for network access. |

Enable the Pi hardware UART — see [step 1a below](#1a--enable-uart).

---

## Wiring Diagram

### Power supply chain

```
12 V DC PSU (≥ 3 A)
├── 12 V ──────────────────────────────── Weight Indicator Module (10–28 V DC input)
└── 12 V ──→ Buck Converter (12 V → 5 V) ──→ Raspberry Pi 5 V
                                               (USB-C on Pi 4/5, or GPIO Pin 2/4)
```

---

### Load cells → Junction box → Weight indicator

```
Load Cell 1 ──┐
Load Cell 2 ──┤                     ┌── E+ ──→ Weight Indicator E+
Load Cell 3 ──┤  Junction Box  ─────┤── E− ──→ Weight Indicator E−
Load Cell 4 ──┘  (Wheatstone        ├── S+ ──→ Weight Indicator S+
                  bridge)           └── S− ──→ Weight Indicator S−
```

---

### RS485 / Modbus RTU chain: Weight indicator → Feiyang module → Pi UART

```
Weight Indicator          Feiyang TTL↔RS485 Module       Raspberry Pi
─────────────────         ────────────────────────        ─────────────────────
RS485 A+ ─────────────── A+                    VCC ─────── Pin  1  (3.3 V)
RS485 B− ─────────────── B−                    GND ─────── Pin  6  (GND)
                                               TXD ─────── Pin 10  (GPIO 15 / RXD)
                                               RXD ─────── Pin  8  (GPIO 14 / TXD)
```

> Auto direction-control — **no DE/RE pin** required.
> Use `/dev/ttyAMA0` (or `/dev/ttyS0` — see step 1a) in `config.yaml`.

---

### I²C LCD display (HD44780 + PCF8574 backpack)

```
LCD Backpack (PCF8574)    Raspberry Pi
──────────────────────    ─────────────────────
VCC ─────────────────────── Pin  2  (5 V)
GND ─────────────────────── Pin  6  (GND)
SDA ─────────────────────── Pin  3  (GPIO 2 / SDA1)
SCL ─────────────────────── Pin  5  (GPIO 3 / SCL1)
```

> Default I²C address: `0x27`. Run `i2cdetect -y 1` to confirm (`0x3F` on some backpacks).

---

### GPIO push buttons

```
Raspberry Pi                      Button          Rail
────────────────────────────────────────────────────────
Pin 11  (GPIO 17) ──┬── [ Analyze button ] ──── GND
                    └── internal pull-up (active LOW on press)

Pin 13  (GPIO 27) ──┬── [ Record button  ] ──── GND
                    └── internal pull-up (active LOW on press)
```

> No external resistor needed — pull-ups are enabled in software via `RPi.GPIO`.
> Any adjacent GND pin (e.g. Pin 9, Pin 14) works for the button return.

---

### USB camera

Plug into any available USB port on the Raspberry Pi.

---

### GPIO summary (all connections at a glance)

```
Pi Physical Pin   BCM GPIO    Function                      Connected to
───────────────   ─────────   ───────────────────────────   ────────────────────────────
Pin  1            —           3.3 V power                   Feiyang VCC
Pin  2            —           5 V power                     LCD backpack VCC
Pin  3            GPIO  2     I²C SDA1                      LCD backpack SDA
Pin  5            GPIO  3     I²C SCL1                      LCD backpack SCL
Pin  6            —           GND                           Feiyang GND / LCD GND
Pin  8            GPIO 14     UART TXD  (→ RS485)           Feiyang RXD
Pin  9            —           GND                           Analyze button (return)
Pin 10            GPIO 15     UART RXD  (← RS485)           Feiyang TXD
Pin 11            GPIO 17     Analyze button (pull-up)      Button → GND
Pin 13            GPIO 27     Record button  (pull-up)      Button → GND
Pin 14            —           GND                           Record button (return)
USB ports         —           USB                           Camera (any USB port)
```

---

## Alternative: Waveshare RS485 TO ETH (B) — Scale over Ethernet

Instead of the Feiyang TTL↔RS485 module wired to the Pi's UART pins, you can use the **[Waveshare RS485 TO ETH (B)](https://www.waveshare.com/wiki/RS485_TO_ETH_(B))** to bridge the weight indicator's RS485 bus onto your LAN. The Pi then reads the scale over Ethernet/Wi-Fi — no UART wiring to the Pi at all.

```
12 V PSU ──── Waveshare RS485 TO ETH (B) ──── Ethernet ──── Router ──── Pi (same LAN)
                  │                                              │
              RS485 A+/B−                             Flask dashboard
                  │
          Weight Indicator Module (Modbus RTU slave)
```

**What changes vs. the default UART wiring:**

| | Default (Feiyang + UART) | This alternative (Waveshare ETH) |
|---|---|---|
| Scale ↔ Pi path | RS485 → Feiyang module → GPIO UART pins | RS485 → Waveshare gateway → LAN → Pi |
| Pi pins used | GPIO 14 (TXD), GPIO 15 (RXD) + 3.3 V, GND | None (LAN only) |
| Protocol on Pi | Modbus RTU over serial (`minimalmodbus`) | Modbus TCP over socket (`pymodbus`) |
| UART enable required | Yes | No |
| Pi location constraint | Must be physically close to scale | Can be anywhere on the same network |

---

### Hardware wiring

```
12 V DC PSU ─────────────────────────────── Waveshare V+ terminal
            └── also powers Weight Indicator and Buck converter → Pi

Weight Indicator RS485 A+ ──────────────── Waveshare 485A terminal
Weight Indicator RS485 B− ──────────────── Waveshare 485B terminal

Waveshare RJ45 ─── Ethernet cable ─── Router / switch
                                           │
                                     Pi (Ethernet or Wi-Fi, same LAN)
```

> The Pi's GPIO UART pins (8/10) and the Feiyang module are no longer needed and can be left unconnected.

---

### Configure the Waveshare gateway

1. **Power it on** and connect it to your router with an Ethernet cable.

2. **Find its IP** — open a browser to `http://192.168.1.200` (factory default).  
   If that doesn't work, use the [VirCom tool](https://files.waveshare.com/upload/4/42/VirCom_en.rar) (Windows) to scan your network and find the device.

3. **Set a static IP** so it always has the same address (recommended):
   - In the web UI, change *IP Address* to e.g. `192.168.1.200`, *Subnet Mask* `255.255.255.0`, *Gateway* to your router IP.
   - Disable DHCP.

4. **Configure the serial port settings** to match the weight indicator:
   - Baud Rate: `9600`
   - Data Bits: `8`
   - Stop Bits: `1`
   - Parity: `None`

5. **Switch to Modbus TCP ↔ RTU mode**:
   - Under *Protocol*, select **Modbus TCP ↔ RTU**.
   - The port number changes to `502` automatically (standard Modbus TCP port).

6. Click **Submit Modification** and wait for the device to restart.

7. **Verify** from the Pi (or any machine on the LAN):

   ```bash
   python3 -c "
   from pymodbus.client import ModbusTcpClient
   c = ModbusTcpClient('192.168.1.200', port=502, timeout=2)
   c.connect()
   r = c.read_holding_registers(address=0, count=2, slave=1)
   print('Net weight regs:', r.registers)
   c.close()
   "
   ```

   You should see two integers printed. If you get an error, check the A+/B− polarity and confirm the weight indicator is powered.

---

### config.yaml changes

Open `config.yaml` and update the `scale:` section:

```yaml
hardware:
  use_mock: false

  scale:
    # Leave port/baud_rate as-is — they are ignored in TCP mode.
    host: "192.168.1.200"   # ← IP of the Waveshare gateway
    tcp_port: 502            # ← 502 = Modbus TCP↔RTU mode
    slave_address: 1
    decimal_places: 0
    unit_to_grams: 1.0
    timeout: 1.0
    sample_rate_hz: 10
```

The `port` and `baud_rate` fields are ignored whenever `host` is non-empty — the system automatically selects the TCP driver.

---

### Install the extra dependency

```bash
pip install -r requirements.txt   # pymodbus is already listed here
```

---

### Calibrating the scale in TCP mode

The calibration script automatically uses the same TCP driver when `host` is set in `config.yaml`:

```bash
python -m scripts.calibrate_scale --known-weight 500
```

---

### Updated GPIO summary (Waveshare ETH mode)

```
Pi Physical Pin   BCM GPIO    Function                  Connected to
───────────────   ─────────   ───────────────────────   ────────────────────────────
Pin  2            —           5 V power                 LCD backpack VCC
Pin  3            GPIO  2     I²C SDA1                  LCD backpack SDA
Pin  5            GPIO  3     I²C SCL1                  LCD backpack SCL
Pin  6            —           GND                       LCD GND
Pin  9            —           GND                       Analyze button (return)
Pin 11            GPIO 17     Analyze button (pull-up)  Button → GND
Pin 13            GPIO 27     Record button  (pull-up)  Button → GND
Pin 14            —           GND                       Record button (return)
USB ports         —           USB                       Camera (any USB port)
RJ45              —           Ethernet                  Router / switch
```

> GPIO 14/15 (UART), Pin 1 (3.3 V), and the Feiyang module are no longer used.

---

## Architecture

```
┌─────────────────────┐   ┌──────────────────────────────────────────┐   ┌────────────┐
│  RS485 Weight       │   │                                          │   │  USB Cam   │
│  Indicator Module   │──▶│              Raspberry Pi                │◀──│            │
│  (Modbus RTU)       │   │                                          │   └────────────┘
└─────────────────────┘   │  Python services                         │
  RS485 ↕ TTL module      │                                          │──▶ SQLite ──▶ Flask + SocketIO ──▶ Browser
  (Feiyang, UART GPIO)     │                                          │
                           └──────────┬────────────┬─────────────────┘
                                      │            │
                               I²C LCD display   GPIO 17 (Analyze btn)
                               (live weight +    GPIO 27 (Record btn)
                                AI detection)
```

A single Python process runs:
1. A background thread polling the weight indicator via **RS485 Modbus RTU** at ~10 Hz — reading the real-time net weight register (registers 0–1, signed 32-bit).
2. A stable-event detector that fires only when the weight is above a threshold **and** stable for a configurable window (ignores oscillation and adjustments).
3. A second background thread running the AI continuously (every 2 s by default), pushing live detection results to the dashboard via Socket.IO — without saving anything. This powers the **"AI sees:"** live panel.
4. A Flask + Flask-SocketIO web server with a live dashboard and analytics page.
5. GPIO edge-detection watching two physical buttons — **Analyze** (GPIO 17) and **Record** (GPIO 27).

## How an Item is Recorded

Recording uses a deliberate **two-step analyze → record** flow so the AI capture and the weight reading happen at the right moments:

```
  Item in front of camera
          │
          ▼
  ┌─ Step 1: Analyze ──────────────────────────────────────────────────────┐
  │  Dashboard button  /api/analyze   ──OR──  Physical GPIO 17 button      │
  │                                                                         │
  │  pipeline.analyze_and_hold()                                           │
  │     ├─ camera.capture()                                                │
  │     ├─ detector.detect_all(frame)                                      │
  │     ├─ save_jpeg(frame, path)  ← image saved NOW before item moves     │
  │     └─ stores PendingDetection(image_path, detections) in memory       │
  │                                                                         │
  │  LCD row 1: detected label + confidence                                │
  │  Dashboard: pending panel shows thumbnail + label + confidence         │
  └─────────────────────────────────────────────────────────────────────── ┘
          │
          ▼  move item to scale, wait for weight to stabilise
          │
  ┌─ Step 2: Record Weight ────────────────────────────────────────────────┐
  │  Dashboard button  /api/commit   ──OR──  Physical GPIO 27 button       │
  │                                                                         │
  │  pipeline.commit_pending()                                             │
  │     ├─ reads current live weight_g from scale                          │
  │     ├─ db.insert_event(pending image, detections, weight_g)            │
  │     └─ socketio.emit("new_event") → dashboard updates live             │
  │                                                                         │
  │  PendingDetection is consumed and cleared                              │
  └─────────────────────────────────────────────────────────────────────── ┘

Background loops (always running):
  Scale polling  (~10 Hz)    →  StableEventDetector → LCD weight row updates at ~2 Hz
  AI preview     (every 2 s) →  broadcast_ai_preview() → Socket.IO "AI sees:" panel
```

**Important rules:**

| Rule | Detail |
|---|---|
| Analyze before Record | You must press **Analyze** before **Record Weight**. The Record button is disabled until a pending detection exists. |
| Image captured at Analyze time | The JPEG is saved when Analyze is pressed, so it captures the item in front of the camera — not after it has been moved to the scale. |
| Event skipped if nothing detected | If the AI finds no recognisable object the pending state is not set and the Record button stays disabled. |
| Clear pending | Use the **✕ Clear** button (dashboard) or press Analyze again to discard a pending detection without recording. |
| Live "AI sees:" panel | Updates automatically every 2 s via Socket.IO without saving anything — shows all model predictions including low-confidence labels. Interval controlled by `ai.ai_preview_interval_s` (set to `0` to disable). |
| Weight split equally | If multiple objects are detected in one frame the total weight is divided equally between them. |
| Reset required between events | After an event fires the weight must drop below `reset_threshold_g` (default 2 g) before the stable-event detector resets. |
| Bin capacity check | If the total weight reaches `events.capacity_kg` the pipeline pauses and the dashboard shows a "bin full" warning. |
| Legacy Record Now | The original **Record Now** button (`POST /api/record`) still works — it commits the pending detection if one exists, otherwise falls back to a fresh capture + record in one step. |
---

## Project Layout

```
.
├── run.py                       # entrypoint — wires pipeline, LCD, buttons, Flask
├── config.example.yaml          # copy to config.yaml and edit
├── requirements.txt             # base deps (work on any OS) — includes minimalmodbus + pyserial
├── requirements-pi.txt          # Pi-only deps — ai-edge-litert, RPLCD, smbus2, RPi.GPIO
├── app/
│   ├── config.py                # YAML config loader — ScaleConfig, LCDConfig, ButtonConfig
│   ├── hardware/
│   │   ├── scale.py             # ModbusRTUScale / ModbusTCPScale drivers
│   │   ├── camera.py            # USB camera driver
│   │   ├── lcd.py               # I2CLCD / MockLCD — HD44780 over PCF8574 I2C backpack
│   │   ├── button.py            # ButtonWatcher / MockButton — GPIO edge detection
│   │   └── mock.py              # MockScale, MockCamera (development without Pi)
│   ├── ai/                      # Detector interface, TFLite impl, label maps
│   ├── core/
│   │   ├── pipeline.py          # Orchestration — analyze_and_hold(), commit_pending()
│   │   ├── db.py                # SQLAlchemy models + queries
│   │   └── events.py            # WasteEvent, Detection, PendingDetection dataclasses
│   ├── web/
│   │   ├── routes.py            # Flask routes + Socket.IO handlers
│   │   ├── server.py            # Flask app factory
│   │   └── templates/
│   │       ├── dashboard.html   # live weight + two-step Analyze/Record UI + camera feed
│   │       ├── analytics.html   # charts
│   │       ├── settings.html    # database reset page
│   │       └── base.html
│   └── utils/                   # logging
├── scripts/
│   ├── calibrate_scale.py       # interactive zero + weight-point calibration via Modbus
│   ├── download_model.py        # fetches EfficientDet-Lite0 TFLite model
│   └── install_service.sh       # installs + enables the systemd service
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
sudo apt install -y python3-pip python3-venv python3-opencv libopenblas-dev i2c-tools
```

### 1a — Enable UART

The weight indicator communicates over RS485 via the Pi's hardware UART. You must enable it and disable the serial console that occupies it by default.

**Option A — raspi-config (easiest)**

```bash
sudo raspi-config
```

Navigate to *Interface Options* → *Serial Port*:
- **"Would you like a login shell to be accessible over serial?"** → **No**
- **"Would you like the serial port hardware to be enabled?"** → **Yes**

Finish, then reboot:

```bash
sudo reboot
```

**Option B — manual (Bookworm / Trixie)**

```bash
# Disable the serial console
sudo sed -i 's/console=serial0,[0-9]* //' /boot/firmware/cmdline.txt

# Enable the UART hardware
grep -q 'enable_uart=1' /boot/firmware/config.txt \
  || echo 'enable_uart=1' | sudo tee -a /boot/firmware/config.txt

sudo reboot
```

> **Pi 4 / Pi 5 — Bluetooth conflict:** On Pi 4 and Pi 5, `/dev/ttyAMA0` is assigned to Bluetooth by default. Either disable Bluetooth (`dtoverlay=disable-bt` in `/boot/firmware/config.txt`) to free `/dev/ttyAMA0`, or use `/dev/ttyS0` instead and update `config.yaml` accordingly.

After reboot, confirm the port is available:

```bash
ls /dev/ttyAMA0   # should exist after enabling UART
```

### 1b — Enable I²C (for the LCD)

```bash
sudo raspi-config
# Interface Options → I2C → Yes → Finish → Reboot
```

After reboot, verify the LCD is detected:

```bash
i2cdetect -y 1
# You should see 27 or 3f in the grid
```

> If nothing appears, check VCC/GND/SDA/SCL wiring and confirm the backpack address matches `hardware.lcd.i2c_address` in `config.yaml`.

### 2 — Verify the RS485 module is detected

With the Feiyang module wired up and the Pi rebooted, check the port is accessible:

```bash
python3 -c "
import minimalmodbus, serial
i = minimalmodbus.Instrument('/dev/ttyAMA0', 1)
i.serial.baudrate = 9600
i.serial.timeout = 1
print('Net weight raw:', i.read_registers(0, 2, functioncode=3))
"
```

You should see two integers printed. If you get a `NoResponseError`, check A+/B− polarity and that the module is powered.

> If using `/dev/ttyS0` instead, replace the port string above and in `config.yaml`.

### 3 — Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-pi.txt
```

> **Note:** Raspberry Pi OS Bookworm/Trixie enforces an externally-managed Python environment.
> Always use a venv — never install packages system-wide with `pip` on the Pi.

### 4 — Download the TFLite model

```bash
python -m scripts.download_model
```

### 5 — Configure

**Step 1 — make a copy of the example config file**

```bash
cp config.example.yaml config.yaml
```

This creates your personal `config.yaml` from the provided template. You only edit `config.yaml` — never the `config.example.yaml` original.

---

**Step 2 — open the file in a text editor**

`nano` is a simple text editor built into Raspberry Pi OS. Type:

```bash
nano config.yaml
```

The file will open right in the terminal. You can scroll up/down with the arrow keys.

---

**Step 3 — change these two settings**

Find the line that says `use_mock: true` and change it to `false`:

```yaml
hardware:
  use_mock: false        # ← change true to false (tells the system to use real hardware)
```

Find the line that says `backend: mock` and change it to the AI backend you want to use:

```yaml
# Option A — EfficientDet-Lite0 COCO model (downloaded in step 4)
ai:
  backend: tflite
  model_path: app/ai/models/efficientdet_lite0.tflite
  labels_path: app/ai/models/coco_labels.txt
  input_size: 320

# Option B — Your own Teachable Machine model (see „Training a Waste Classifier“ below)
ai:
  backend: classification
  model_path: app/ai/models/waste_classifier.tflite
  labels_path: app/ai/models/waste_labels.txt
  input_size: 224
```

> **What is a YAML file?** It is a plain settings file. Each line is `setting-name: value`.  
> Lines that start with `#` are comments — they are ignored by the program, they are just notes for you.  
> **Indentation matters** — do not add or remove the spaces at the start of lines.

---

**Step 4 — save and exit nano**

1. Press **Ctrl + O** (the letter O, not zero) — this saves the file. Press **Enter** to confirm the filename.
2. Press **Ctrl + X** — this closes nano and returns you to the terminal.

---

**Step 5 — verify it saved correctly** *(optional but recommended)*

```bash
cat config.yaml
```

This prints the file so you can check your changes look right.

### 6 — Calibrate the scale

Calibration is performed on the weight indicator module itself via Modbus commands — no `config.yaml` values are stored. Run the calibration script on the Pi:

```bash
python -m scripts.calibrate_scale --known-weight 500
```

Follow the prompts:
1. Remove all weight from the platform → press Enter (sends zero-calibration command to module).
2. Place the known reference weight → press Enter (sends weight-point calibration command).

The `--known-weight` value is in the module's calibrated unit. If `unit_to_grams=1000.0` (kg), pass the weight in kg (e.g. `--known-weight 0.5` for 500 g).

> **Decimal places:** If your module is configured for 2 decimal places in kg, set `decimal_places: 2` and `unit_to_grams: 1000.0` in `config.yaml` before calibrating.

### 7 — Start the system

```bash
python run.py
```

You will see a line in the output like:

```
Web server listening on http://0.0.0.0:5000
```

> **Do not** type `http://0.0.0.0:5000` into your browser — that address means  
> "listen on every network interface" and cannot be opened directly.

**Find the Pi's real IP address** (open a second terminal or run this before starting):

```bash
hostname -I
```

This prints something like `192.168.1.105`. Use that number.

**Then open the dashboard:**

| Where you are | Address to type in your browser |
|---|---|
| On the Pi itself | `http://localhost:5000` |
| On another device (phone, laptop) on the same Wi-Fi | `http://192.168.1.105:5000` *(use your actual IP from `hostname -I`)* |
| Using hostname (after mDNS setup) | `http://Waste-Monitoring.local:5000` |

> **Tip:** To keep the server running after you close the terminal, see
> [Auto-start on boot](#auto-start-on-boot-systemd) or run it with `nohup python run.py &`.

---

## Accessing by Hostname (mDNS / .local)

Instead of typing an IP address, you can give the Pi a memorable hostname reachable as `http://Waste-Monitoring.local:5000` from any device on the same network — no internet required, works over both Wi-Fi and Ethernet.

### 1 — Install Avahi and set the hostname

```bash
sudo apt install -y avahi-daemon
sudo hostnamectl set-hostname Waste-Monitoring
```

### 2 — Fix /etc/hosts (prevents sudo warnings)

```bash
sudo sed -i "s/127.0.1.1.*/127.0.1.1\tWaste-Monitoring/" /etc/hosts
```

### 3 — Enable Avahi and reboot

```bash
sudo systemctl enable --now avahi-daemon
sudo reboot
```

After reboot, from any device on the same network:

```
http://Waste-Monitoring.local:5000
```

> **Windows:** mDNS (`.local`) is supported natively on Windows 10/11, macOS, iOS, and Android.
> If it does not resolve on an older Windows machine, install [Bonjour Print Services](https://support.apple.com/kb/DL999) (free).

### Optional — remove the port number

To access as just `http://Waste-Monitoring.local`, bind Flask to port 80 using `authbind`:

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

Then reinstall the service (the install script handles `authbind` automatically when port 80 is configured):

```bash
sudo bash scripts/install_service.sh
```

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

Run via authbind directly:

```bash
authbind --deep venv/bin/python run.py
```

Or reinstall the systemd service — `install_service.sh` detects port 80 automatically:

```bash
sudo bash scripts/install_service.sh
```

Now the dashboard is reachable at:

```
http://192.168.1.100
```

---

## Auto-start on boot (systemd)

A setup script is provided that auto-detects the project path, venv, and current user:

```bash
sudo bash scripts/install_service.sh
```

This creates and enables `/etc/systemd/system/waste-monitor.service` automatically.

Useful commands after installation:

```bash
sudo systemctl status waste-monitor      # check if running
sudo systemctl restart waste-monitor     # restart after config changes
sudo systemctl stop waste-monitor        # stop
sudo systemctl disable waste-monitor     # remove from autostart
journalctl -u waste-monitor -f           # live logs
```

To run as a different user (e.g. not `pi`):

```bash
WASTE_USER=myuser sudo bash scripts/install_service.sh
```

---

## Deploying a New Build

Use this workflow every time you push updated code to the Pi.

### Option A — Git pull + service restart (recommended)

```bash
cd ~/IoT-Enabled-Waste-Monitoring-and-Characterization-System-with-Real-Time-Dashboard-and-Analytics
git pull
source venv/bin/activate
pip install -r requirements.txt -r requirements-pi.txt   # only needed if dependencies changed
sudo systemctl restart waste-monitor
```

Check it came back up:
```bash
sudo systemctl status waste-monitor
```

Watch live logs to confirm no errors:
```bash
journalctl -u waste-monitor -f
```

### Option B — Copy files manually (no Git on Pi)

From your **laptop / dev machine**, copy the updated project over SSH:

```powershell
# Windows (PowerShell) — run from the project root
scp -r . pi@Waste-Monitoring.local:~/IoT-Enabled-Waste-Monitoring-and-Characterization-System-with-Real-Time-Dashboard-and-Analytics/
```

```bash
# macOS / Linux
rsync -av --exclude '.venv' --exclude '__pycache__' --exclude 'data/' \
  ./ pi@Waste-Monitoring.local:~/IoT-Enabled-Waste-Monitoring-and-Characterization-System-with-Real-Time-Dashboard-and-Analytics/
```

Then SSH in and restart:

```bash
ssh pi@Waste-Monitoring.local
cd ~/IoT-Enabled-Waste-Monitoring-and-Characterization-System-with-Real-Time-Dashboard-and-Analytics
source venv/bin/activate
pip install -r requirements.txt -r requirements-pi.txt   # only if deps changed
sudo systemctl restart waste-monitor
sudo systemctl status waste-monitor
```

### Full reboot (only if required)

A plain service restart is enough for code changes. Only do a full reboot if you changed hardware wiring, the Pi's hostname, or a system-level config:

```bash
sudo reboot
```

The service starts automatically on boot (systemd). Wait ~30 seconds, then open:

```
http://Waste-Monitoring.local:5000
```

---

## Configuration Reference

All settings live in `config.yaml` (see `config.example.yaml` for the full annotated template).

| Key | Default | Description |
|---|---|---|
| `hardware.use_mock` | `true` | `false` to use real RS485 scale + USB camera |
| `hardware.scale.port` | `/dev/ttyUSB0` | Serial port for the RS485 adapter. Use `/dev/ttyAMA0` (Pi UART via GPIO) or `/dev/ttyS0`. Ignored when `host` is set. |
| `hardware.scale.slave_address` | `1` | Modbus slave address programmed on the weight indicator module |
| `hardware.scale.baud_rate` | `9600` | Must match the module setting — supports 9600 / 19200 / 38400. Ignored when `host` is set. |
| `hardware.scale.decimal_places` | `0` | Decimal places encoded in the register value. Raw integer ÷ 10ⁿ before applying `unit_to_grams` |
| `hardware.scale.unit_to_grams` | `1.0` | Multiply (raw / 10^decimal_places) by this to get grams. Use `1000.0` if module is calibrated in kg |
| `hardware.scale.timeout` | `1.0` | Modbus reply timeout in seconds |
| `hardware.scale.sample_rate_hz` | `10` | Target polling rate |
| `hardware.scale.host` | `""` | IP address of an RS485-to-Ethernet gateway (e.g. Waveshare RS485 TO ETH (B)). When non-empty, uses Modbus TCP instead of serial RTU. |
| `hardware.scale.tcp_port` | `502` | TCP port of the gateway. Use `502` in Modbus TCP↔RTU mode, `4196` for raw transparent TCP. |
| `hardware.lcd.enabled` | `false` | `true` to enable the I²C LCD display |
| `hardware.lcd.i2c_address` | `0x27` | PCF8574 backpack I²C address (use `i2cdetect -y 1` to confirm) |
| `hardware.lcd.cols` | `16` | Number of character columns (16 or 20) |
| `hardware.lcd.rows` | `2` | Number of character rows (2 or 4) |
| `hardware.lcd.i2c_port` | `1` | I²C bus number (1 on all modern Pi) |
| `hardware.button_analyze.enabled` | `false` | `true` to activate the physical Analyze button |
| `hardware.button_analyze.gpio_pin` | `17` | BCM GPIO pin for the Analyze button |
| `hardware.button_analyze.debounce_ms` | `300` | Software debounce window in milliseconds |
| `hardware.button_analyze.mock_interval_s` | `0.0` | Auto-fire interval in mock mode (`0` = disabled) |
| `hardware.button_record.enabled` | `false` | `true` to activate the physical Record button |
| `hardware.button_record.gpio_pin` | `27` | BCM GPIO pin for the Record button |
| `hardware.button_record.debounce_ms` | `300` | Software debounce window in milliseconds |
| `hardware.button_record.mock_interval_s` | `0.0` | Auto-fire interval in mock mode (`0` = disabled) |
| `events.min_weight_g` | `5.0` | Minimum weight (g) to start a placement event |
| `events.stability_window` | `8` | Consecutive samples that must be within `stability_g` stddev |
| `events.stability_g` | `1.0` | Max stddev (g) to declare a stable reading |
| `events.reset_threshold_g` | `2.0` | Weight must drop below this to reset after an event |
| `events.capacity_kg` | `100.0` | Bin capacity — pipeline pauses when exceeded |
| `ai.backend` | `mock` | `mock` / `tflite` (COCO object detection) / `classification` (Teachable Machine) |
| `ai.model_path` | — | Path to `.tflite` model file |
| `ai.labels_path` | — | Path to newline-separated labels file |
| `ai.input_size` | `320` | Input image size in pixels (square). Use `224` for Teachable Machine models. |
| `ai.min_confidence` | `0.4` | Minimum detection confidence (0–1) |
| `database.url` | SQLite | SQLAlchemy URL (supports Postgres/MySQL too) |
| `web.host` / `web.port` | `0.0.0.0:5000` | Flask bind address |

---

## Web API

| Route | Description |
|---|---|
| `GET /` | Live dashboard — weight, scale status bar, camera feed, latest item, two-step Analyze / Record Weight buttons |
| `GET /analytics` | Charts (per-category weight/counts, daily totals) |
| `GET /settings` | Settings page — database reset |
| `GET /api/events?limit=&offset=&category=&since=&until=` | List events (JSON) |
| `GET /api/summary?window=all\|today\|week` | Aggregate stats |
| `GET /api/daily?days=N` | Daily totals for the last N days |
| `GET /api/categories` | Category list |
| `GET /api/bin_status` | Current bin-full state and capacity |
| `POST /api/analyze` | **Step 1** — capture frame, run AI, save image, store pending detection. Returns `{status, label, category, confidence, image_path, all_detections}` or `{status: "no_detection"}` |
| `POST /api/commit` | **Step 2** — read live weight, write DB row using pending detection, clear pending. Returns `{status: "recorded", weight_g}` or HTTP 409 if no pending detection |
| `GET /api/pending_detection` | Returns `{pending: bool, label, category, confidence, image_path}` — use to restore UI state on page reload |
| `POST /api/record` | Legacy one-shot record — commits pending if one exists, otherwise fresh capture + record in a single step |
| `POST /api/reset_db` | Delete all events and images, returns `{"deleted": N}` |
| `GET /api/events.csv` | Export all events as CSV |
| `GET /images/<event_id>` | Captured image for an event |
| `GET /video_feed` | MJPEG live camera stream |
| Socket.IO `weight` | Live weight stream (~10 Hz) |
| Socket.IO `scale_status` | Scale detector state (idle/stabilizing/cooldown + progress) |
| Socket.IO `new_event` | Pushed when a new placement is recorded |
| Socket.IO `bin_status` | Pushed when bin-full state changes |

---

## Training a Waste Classifier

The default EfficientDet-Lite0 model is trained on generic COCO objects (bottles, cans, forks, etc.) and will return "no detection" for items it doesn't recognise. For better accuracy, train your own classifier on photos of your actual waste items using **Google Teachable Machine** — no code required, takes about 15 minutes.

### Why Teachable Machine?

| | EfficientDet-Lite0 (COCO) | Teachable Machine |
|---|---|---|
| Setup | Download once | 15 min training |
| Trained on | Generic objects | **Your actual items** |
| Accuracy for waste | Moderate | High |
| Exportable to TFLite | Yes (pre-made) | Yes (one click) |

### Step 1 — Collect images

Go to **https://teachablemachine.withgoogle.com** → *Get Started* → *Image Project* → *Standard image model*.

Create one class per category. Name them **exactly**:

```
plastic
paper
metal
glass
organic
```

> The system matches these names directly to waste categories. Spelling and case matter.

Collect photos using your webcam or upload images. Aim for **40–80 photos per class**, taken under your actual lighting conditions with your actual waste items.

Tips for better accuracy:
- Rotate the item and photograph it from multiple angles
- Include a few photos with similar-looking items from the *wrong* class (helps the model learn differences)
- Keep the camera distance and background consistent with how the system will be used

### Step 2 — Train the model

Click **Train Model**. Training takes 30–90 seconds in the browser. Once done, preview the model live with your webcam to check accuracy.

### Step 3 — Export

Click **Export Model** → *TensorFlow Lite* tab → select **Floating Point** → click **Download my model**.

You receive a `.zip` file containing:
- `model.tflite` — the trained model
- `labels.txt` — one class name per line

### Step 4 — Deploy to the Pi

Copy both files to the Pi:

```powershell
# Windows — from the project root
scp model.tflite pi@Waste-Monitoring.local:~/IoT-Enabled-Waste-Monitoring-and-Characterization-System-with-Real-Time-Dashboard-and-Analytics/app/ai/models/waste_classifier.tflite
scp labels.txt   pi@Waste-Monitoring.local:~/IoT-Enabled-Waste-Monitoring-and-Characterization-System-with-Real-Time-Dashboard-and-Analytics/app/ai/models/waste_labels.txt
```

```bash
# macOS / Linux
scp model.tflite labels.txt pi@Waste-Monitoring.local:~/IoT-Enabled-Waste-Monitoring-and-Characterization-System-with-Real-Time-Dashboard-and-Analytics/app/ai/models/
```

### Step 5 — Update config.yaml

SSH into the Pi and edit `config.yaml`:

```bash
nano config.yaml
```

Change the `ai:` section to:

```yaml
ai:
  backend: classification
  model_path: app/ai/models/waste_classifier.tflite
  labels_path: app/ai/models/waste_labels.txt
  input_size: 224          # Teachable Machine exports expect 224×224
  min_confidence: 0.6      # raise threshold — classifier is more decisive than detector
```

Save (`Ctrl+O`, `Ctrl+X`) and restart:

```bash
sudo systemctl restart waste-monitor
```

### Retraining

Repeat steps 1–5 whenever you want to add items or improve accuracy. You can keep the old model file as a backup by renaming it before replacing it:

```bash
mv app/ai/models/waste_classifier.tflite app/ai/models/waste_classifier_v1.tflite
```

---

## Tests

```bash
pip install -r requirements.txt
pytest -v
```

The test suite uses the mock scale, mock camera, and mock detector — no hardware required.

---

## Extending

* **Train a waste-specific classifier:** see [Training a Waste Classifier](#training-a-waste-classifier) above. Use Google Teachable Machine to train on your own items and switch to the `classification` backend.
* **Add more categories:** edit `DEFAULT_CATEGORIES` in `app/core/db.py` and add matching entries to `LABEL_TO_CATEGORY` in `app/ai/labels.py`.
* **Different DB:** point `database.url` at Postgres/MySQL — the SQLAlchemy layer handles it.
* **Enable the LCD:** set `hardware.lcd.enabled: true` in `config.yaml`. For a 20×4 display also set `cols: 20` and `rows: 4`. The display updates the weight row at ~2 Hz and the detection row whenever the AI preview fires or Analyze is pressed.
* **Enable physical buttons:** set `hardware.button_analyze.enabled: true` and `hardware.button_record.enabled: true` in `config.yaml`. Wire each button normally-open between the GPIO pin and GND — the driver enables the internal pull-up resistor.
* **Read stable weight instead of real-time:** call `scale.read_stable_grams()` instead of `scale.read_grams()` in `app/core/pipeline.py` if you want the module's own stable-hold register instead of the raw real-time register.
* **Calibrate the scale:** run `python -m scripts.calibrate_scale --known-weight <grams>` on the Pi — calibration is stored on the module, not in `config.yaml`.
* **Reset database via UI:** go to `/settings` and click **Reset Database** to clear all events and images (useful during testing).
* **Two-step flow:** press **Analyze** with the item in front of the camera (captures + detects), then move the item to the scale and press **Record Weight** to pair the AI result with the live weight. The **✕ Clear** button discards a pending detection without recording.
* **Diagnose scale issues:** the Live Weight card on the dashboard shows a real-time stability progress bar and the current detector state (idle / stabilizing / cooldown).
