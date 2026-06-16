"""Interactive calibration helper for the RS485 Modbus RTU weight indicator module.

Usage on the Raspberry Pi:
    python -m scripts.calibrate_scale --known-weight 500

Steps performed:
  1. Send a zero-calibration command (empty scale must be on the load cell).
  2. Ask you to place a known weight, then send a weight-point calibration command.

All calibration is handled internally by the module — no config values need to
be stored in config.yaml (tare and calibration state live on the device).

For decimal places / unit configuration, edit config.yaml under hardware.scale:
  decimal_places: 0        # 0 = raw grams, 2 = e.g. kg with 2 decimal places
  unit_to_grams: 1.0       # 1.0 = grams, 1000.0 = kg
"""

from __future__ import annotations

import argparse
import sys
import time

from app.config import load_config
from app.utils import setup_logging, get_logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RS485 Modbus RTU weight module zero + weight-point calibration"
    )
    parser.add_argument(
        "--known-weight",
        type=float,
        required=True,
        help=(
            "Known reference weight expressed in the module's calibrated unit "
            "(grams if unit_to_grams=1.0, kg if unit_to_grams=1000.0)."
        ),
    )
    parser.add_argument("-c", "--config", help="Path to config.yaml")
    args = parser.parse_args(argv)

    setup_logging("INFO")
    log = get_logger("calibrate")
    cfg = load_config(args.config)

    if cfg.hardware.use_mock:
        print(
            "ERROR: hardware.use_mock is true in config. Set it to false before calibrating.",
            file=sys.stderr,
        )
        return 2

    from app.hardware.scale import ModbusRTUScale

    sc = cfg.hardware.scale
    scale = ModbusRTUScale(
        port=sc.port,
        slave_address=sc.slave_address,
        baud_rate=sc.baud_rate,
        decimal_places=sc.decimal_places,
        unit_to_grams=sc.unit_to_grams,
        timeout=sc.timeout,
    )

    # ---- Step 1: Zero calibration ----------------------------------------
    input("Remove ALL weight from the scale, then press Enter to send zero calibration…")
    time.sleep(0.5)
    scale.zero_calibrate()
    time.sleep(1.0)  # Give module time to complete calibration
    reading_empty = scale.read_grams()
    print(f"Zero calibration sent. Current reading: {reading_empty:.2f} g  (should be ~0)")

    # ---- Step 2: Weight-point calibration ----------------------------------
    input(
        f"\nPlace the known weight ({args.known_weight} {_unit_label(sc.unit_to_grams)}) "
        f"on the scale, then press Enter to send weight-point calibration…"
    )
    time.sleep(0.5)

    # Convert known_weight (in module's unit) to the raw integer the module expects
    # raw = known_weight * 10**decimal_places  (inverse of the read conversion)
    known_raw = round(args.known_weight * (10 ** sc.decimal_places))
    scale.weight_point_calibrate(known_raw)
    time.sleep(1.0)

    reading_loaded = scale.read_grams()
    print(f"Weight-point calibration sent. Current reading: {reading_loaded:.2f} g")
    print(
        f"Expected: {args.known_weight * sc.unit_to_grams:.2f} g  —  "
        f"Error: {abs(reading_loaded - args.known_weight * sc.unit_to_grams):.2f} g"
    )
    print("\nCalibration complete. No config.yaml changes required.")
    scale.close()
    return 0


def _unit_label(unit_to_grams: float) -> str:
    if unit_to_grams >= 1000.0:
        return "kg"
    return "g"


if __name__ == "__main__":
    raise SystemExit(main())
