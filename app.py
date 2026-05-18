from __future__ import annotations

import json
import os
import random
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List


WASTE_CLASSES = ["plastic", "paper", "metal", "glass", "organic", "other"]


@dataclass
class Reading:
    timestamp: str
    weight_grams: float
    waste_type: str
    confidence: float


class NAU7802Scale:
    """Reads scale data from NAU7802. Falls back to simulation for local development."""

    def __init__(self, simulate: bool = True) -> None:
        self.simulate = simulate

    def read_weight_grams(self) -> float:
        if self.simulate:
            return round(random.uniform(50.0, 3000.0), 2)

        # Hardware integration point:
        # Read calibrated value from NAU7802 connected to 4 load cells.
        raise RuntimeError("Real NAU7802 integration not configured. Set SIMULATE_HARDWARE=1.")


class USBCamera:
    """Captures image from USB camera; simulated path when unavailable."""

    def __init__(self, simulate: bool = True) -> None:
        self.simulate = simulate
        self.capture_dir = Path("captures")
        self.capture_dir.mkdir(exist_ok=True)

    def capture(self) -> Path:
        file_path = self.capture_dir / f"capture_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.jpg"
        if self.simulate:
            file_path.write_bytes(b"simulated-image")
            return file_path

        # Hardware integration point:
        # Capture frame from USB camera (OpenCV/libcamera etc.) and save to file_path.
        raise RuntimeError("Real USB camera integration not configured. Set SIMULATE_HARDWARE=1.")


class WasteDetector:
    """AI detection wrapper. Uses deterministic fallback for local execution."""

    def detect(self, image_path: Path) -> Dict[str, float | str]:
        # Integration point for local AI model inference (e.g., TFLite on Raspberry Pi).
        idx = hash(image_path.name) % len(WASTE_CLASSES)
        waste_type = WASTE_CLASSES[idx]
        confidence = 0.55 + (idx / (len(WASTE_CLASSES) * 10))
        return {"waste_type": waste_type, "confidence": round(min(confidence, 0.99), 2)}


class WasteMonitoringService:
    def __init__(self, scale: NAU7802Scale, camera: USBCamera, detector: WasteDetector) -> None:
        self.scale = scale
        self.camera = camera
        self.detector = detector
        self._readings: List[Reading] = []
        self._lock = threading.Lock()

    def sample(self) -> Reading:
        weight = self.scale.read_weight_grams()
        image_path = self.camera.capture()
        detection = self.detector.detect(image_path)

        reading = Reading(
            timestamp=datetime.now(timezone.utc).isoformat(),
            weight_grams=weight,
            waste_type=str(detection["waste_type"]),
            confidence=float(detection["confidence"]),
        )

        with self._lock:
            self._readings.append(reading)
        return reading

    def get_readings(self) -> List[Reading]:
        with self._lock:
            return list(self._readings)

    def analytics(self) -> Dict[str, object]:
        readings = self.get_readings()
        total_weight = sum(r.weight_grams for r in readings)
        by_type: Dict[str, float] = {w: 0.0 for w in WASTE_CLASSES}
        for reading in readings:
            by_type[reading.waste_type] += reading.weight_grams

        sample_count = len(readings)
        avg_weight = round(total_weight / sample_count, 2) if sample_count else 0.0

        return {
            "sample_count": sample_count,
            "total_weight_grams": round(total_weight, 2),
            "average_weight_grams": avg_weight,
            "by_type_grams": {k: round(v, 2) for k, v in by_type.items()},
        }


def build_dashboard_html() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Waste Monitoring Dashboard</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f6f8fa; color: #111; }
    .cards { display: grid; grid-template-columns: repeat(3, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .card { background: white; border-radius: 8px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
    button { background: #0a7; color: white; border: 0; border-radius: 6px; padding: 10px 14px; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; background: white; margin-top: 16px; }
    th, td { border: 1px solid #ddd; padding: 8px; font-size: 14px; }
    .bars { margin-top: 16px; background: white; padding: 12px; border-radius: 8px; }
    .bar-row { display: grid; grid-template-columns: 120px 1fr 60px; align-items: center; gap: 8px; margin: 6px 0; }
    .bar { background: #d9f2ea; height: 14px; border-radius: 4px; overflow: hidden; }
    .bar > div { height: 14px; background: #0a7; }
  </style>
</head>
<body>
  <h1>Local Waste Monitoring Dashboard</h1>
  <p>Raspberry Pi local mode (NAU7802 + USB Camera + AI detection pipeline)</p>
  <button id=\"sample-btn\">Capture Waste Sample</button>

  <div class=\"cards\">
    <div class=\"card\"><strong>Samples</strong><div id=\"sample-count\">0</div></div>
    <div class=\"card\"><strong>Total Weight (g)</strong><div id=\"total-weight\">0</div></div>
    <div class=\"card\"><strong>Average Weight (g)</strong><div id=\"avg-weight\">0</div></div>
  </div>

  <div class=\"bars\" id=\"bars\"></div>

  <table>
    <thead><tr><th>Time (UTC)</th><th>Waste Type</th><th>Confidence</th><th>Weight (g)</th></tr></thead>
    <tbody id=\"rows\"></tbody>
  </table>

  <script>
    async function refresh() {
      const [readingsRes, analyticsRes] = await Promise.all([
        fetch('/api/readings'),
        fetch('/api/analytics')
      ]);
      const readings = await readingsRes.json();
      const analytics = await analyticsRes.json();

      document.getElementById('sample-count').textContent = analytics.sample_count;
      document.getElementById('total-weight').textContent = analytics.total_weight_grams;
      document.getElementById('avg-weight').textContent = analytics.average_weight_grams;

      const rows = document.getElementById('rows');
      rows.innerHTML = readings.slice().reverse().map(r =>
        `<tr><td>${r.timestamp}</td><td>${r.waste_type}</td><td>${r.confidence}</td><td>${r.weight_grams}</td></tr>`
      ).join('');

      const byType = analytics.by_type_grams || {};
      const maxVal = Math.max(1, ...Object.values(byType));
      const bars = document.getElementById('bars');
      bars.innerHTML = Object.entries(byType).map(([k, v]) => {
        const pct = Math.round((v / maxVal) * 100);
        return `<div class=\"bar-row\"><div>${k}</div><div class=\"bar\"><div style=\"width:${pct}%\"></div></div><div>${v}</div></div>`;
      }).join('');
    }

    document.getElementById('sample-btn').addEventListener('click', async () => {
      await fetch('/api/sample', { method: 'POST' });
      await refresh();
    });

    refresh();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    service: WasteMonitoringService

    def _json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = build_dashboard_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/readings":
            self._json([asdict(r) for r in self.service.get_readings()])
            return

        if self.path == "/api/analytics":
            self._json(self.service.analytics())
            return

        self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/sample":
            reading = self.service.sample()
            self._json(asdict(reading), status=HTTPStatus.CREATED)
            return

        self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        # Keep local dashboard logs quiet.
        return


def main() -> None:
    simulate_hardware = os.getenv("SIMULATE_HARDWARE", "1") == "1"
    port = int(os.getenv("PORT", "8080"))

    service = WasteMonitoringService(
        scale=NAU7802Scale(simulate=simulate_hardware),
        camera=USBCamera(simulate=simulate_hardware),
        detector=WasteDetector(),
    )

    Handler.service = service
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Waste monitoring dashboard running at http://127.0.0.1:{port} (simulate={simulate_hardware})")
    server.serve_forever()


if __name__ == "__main__":
    main()
