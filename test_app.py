import unittest
from pathlib import Path

from app import WasteMonitoringService, Reading


class FakeScale:
    def read_weight_grams(self):
        return 500.0


class FakeCamera:
    def capture(self):
        return Path("fake.jpg")


class FakeDetector:
    def detect(self, image_path):
        return {"waste_type": "plastic", "confidence": 0.92}


class WasteMonitoringServiceTests(unittest.TestCase):
    def test_sample_creates_reading(self):
        service = WasteMonitoringService(FakeScale(), FakeCamera(), FakeDetector())

        reading = service.sample()

        self.assertEqual(reading.weight_grams, 500.0)
        self.assertEqual(reading.waste_type, "plastic")
        self.assertEqual(reading.confidence, 0.92)
        self.assertEqual(len(service.get_readings()), 1)

    def test_analytics_sums_weight_by_type(self):
        service = WasteMonitoringService(FakeScale(), FakeCamera(), FakeDetector())
        service._readings = [
            Reading("2026-01-01T00:00:00+00:00", 100.0, "plastic", 0.9),
            Reading("2026-01-01T00:00:01+00:00", 200.0, "paper", 0.8),
            Reading("2026-01-01T00:00:02+00:00", 50.0, "plastic", 0.7),
        ]

        analytics = service.analytics()

        self.assertEqual(analytics["sample_count"], 3)
        self.assertEqual(analytics["total_weight_grams"], 350.0)
        self.assertEqual(analytics["average_weight_grams"], round(350.0 / 3, 2))
        self.assertEqual(analytics["by_type_grams"]["plastic"], 150.0)
        self.assertEqual(analytics["by_type_grams"]["paper"], 200.0)


if __name__ == "__main__":
    unittest.main()
