# IoT-Enabled Waste Monitoring and Characterization (Local Prototype)

This repository now includes a **local-first prototype** for a smart waste scale system using:

- Raspberry Pi runtime target
- NAU7802 + 4 load cells (integration point)
- USB camera capture (integration point)
- AI waste detection pipeline (integration point)
- Local dashboard + analytics web app

## What is implemented

- `app.py` runs a local HTTP server and dashboard at `http://127.0.0.1:8080`
- `/api/sample` triggers one scale reading + image capture + waste classification
- `/api/readings` returns collected samples
- `/api/analytics` returns total, average, and per-waste-type weight analytics
- Simulation mode is enabled by default so it runs locally even without hardware

## Run locally

```bash
python app.py
```

Optional environment variables:

- `PORT` (default: `8080`)
- `SIMULATE_HARDWARE` (`1` default; set `0` for real hardware integration)

## Run tests

```bash
python -m unittest -v
```

## Hardware/AI integration points

For real Raspberry Pi deployment, replace the integration points in `app.py`:

- `NAU7802Scale.read_weight_grams()` for NAU7802 calibrated reads from 4 load cells
- `USBCamera.capture()` for USB camera frame capture
- `WasteDetector.detect()` for local AI model inference (e.g., TFLite)
