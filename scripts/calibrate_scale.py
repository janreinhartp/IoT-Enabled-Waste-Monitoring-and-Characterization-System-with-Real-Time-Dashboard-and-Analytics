"""Interactive scale tare + calibration helper for the NAU7802.

Usage on the Raspberry Pi:
    python -m scripts.calibrate_scale --known-weight 500

This will:
  1. Ask you to clear the scale, then capture a tare offset.
  2. Ask you to place a known weight, then compute the calibration factor.
  3. Print values you can paste into ``config.yaml`` under ``hardware.scale``.
"""

from __future__ import annotations

import argparse
import sys
import time

from app.config import load_config
from app.utils import setup_logging, get_logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NAU7802 tare + calibration")
    parser.add_argument(
        "--known-weight",
        type=float,
        required=True,
        help="Known reference weight in grams (e.g. 500)",
    )
    parser.add_argument("-c", "--config", help="Path to config.yaml")
    parser.add_argument(
        "--samples", type=int, default=32, help="Samples to average (default 32)"
    )
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

    # Import here so this script can be imported on non-Pi systems for tests.
    from app.hardware.scale import NAU7802Scale

    sc = cfg.hardware.scale
    scale = NAU7802Scale(
        i2c_address=sc.i2c_address,
        gain=sc.gain,
        calibration_factor=1.0,  # use raw counts for calibration
        tare_offset=0,
    )

    input("Remove all weight from the scale, then press Enter to tare…")
    time.sleep(0.5)
    tare = int(scale.read_raw_average(args.samples))
    print(f"Tare offset (raw counts): {tare}")

    input(
        f"Place the known weight ({args.known_weight} g) on the scale, "
        f"then press Enter to calibrate…"
    )
    time.sleep(0.5)
    loaded = scale.read_raw_average(args.samples)
    delta = loaded - tare
    if delta == 0:
        print("ERROR: no change in reading. Check wiring.", file=sys.stderr)
        return 1

    factor = delta / float(args.known_weight)
    print()
    print("=== Add the following to config.yaml under hardware.scale: ===")
    print(f"  tare_offset: {tare}")
    print(f"  calibration_factor: {factor:.4f}")
    print()
    print("Verifying: reading at known weight =", (loaded - tare) / factor, "g")
    scale.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
