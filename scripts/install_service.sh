#!/usr/bin/env bash
# install_service.sh — Install and enable the waste-monitor systemd service.
#
# Usage (run from the project root):
#   bash scripts/install_service.sh
#
# The script auto-detects:
#   - The absolute project directory (WORK_DIR)
#   - The Python executable inside the venv (venv/bin/python)
#   - The current user (USER) — override with: WASTE_USER=myuser bash scripts/install_service.sh

set -euo pipefail

SERVICE_NAME="waste-monitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Resolve paths ─────────────────────────────────────────────────────────────
WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${WORK_DIR}/venv/bin/python"
RUN_SCRIPT="${WORK_DIR}/run.py"
WASTE_USER="${WASTE_USER:-$(whoami)}"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run with sudo."
  echo "  sudo bash scripts/install_service.sh"
  exit 1
fi

if [[ ! -f "${VENV_PYTHON}" ]]; then
  echo "ERROR: venv not found at ${VENV_PYTHON}"
  echo "  Create it first:  python3 -m venv venv && venv/bin/pip install -r requirements.txt -r requirements-pi.txt"
  exit 1
fi

if [[ ! -f "${RUN_SCRIPT}" ]]; then
  echo "ERROR: run.py not found at ${RUN_SCRIPT}"
  exit 1
fi

# ── Write service unit ────────────────────────────────────────────────────────
echo "Installing ${SERVICE_FILE} ..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=IoT Waste Monitor
After=network.target

[Service]
Type=simple
User=${WASTE_USER}
WorkingDirectory=${WORK_DIR}
ExecStart=${VENV_PYTHON} ${RUN_SCRIPT}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "  WorkingDirectory : ${WORK_DIR}"
echo "  ExecStart        : ${VENV_PYTHON} ${RUN_SCRIPT}"
echo "  User             : ${WASTE_USER}"

# ── Enable & start ────────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo ""
echo "✓ Service installed and started."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status  ${SERVICE_NAME}   # check status"
echo "  sudo systemctl restart ${SERVICE_NAME}   # restart after config changes"
echo "  sudo systemctl stop    ${SERVICE_NAME}   # stop"
echo "  sudo systemctl disable ${SERVICE_NAME}   # remove from autostart"
echo "  journalctl -u ${SERVICE_NAME} -f         # live logs"
