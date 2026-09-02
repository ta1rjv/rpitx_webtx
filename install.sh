#!/usr/bin/env bash
# webtx one-command installer for Raspberry Pi OS (Debian-based).
#
# What this does, in order:
#   1. Installs system dependencies (Python, numpy, aiohttp, build tools).
#   2. Builds native/webtx_iq and native/webtx-sendiq if this is an ARM host -
#      against a system librpitx if one is found, otherwise against the
#      copy vendored in this repository (vendor/librpitx, vendor/rpitx-src -
#      see vendor/NOTICE.md and docs/DECISIONS.md ADR-009/ADR-010). No
#      separate rpitx download is needed for this step.
#   3. Optionally clones and installs upstream rpitx (asks first - rpitx's
#      own installer offers to edit /boot/config.txt, a boot-time change).
#      Only useful for rpitx's other, unrelated tools; neither
#      native/webtx_iq nor native/webtx-sendiq need it.
#   4. Generates a self-signed TLS certificate (browsers require HTTPS, or
#      http://localhost, for microphone access).
#   5. Creates webtx.json from webtx.example.json if one does not exist yet.
#
# Safe to re-run: every step skips work that is already done and never
# overwrites an existing webtx.json or certificate.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RPITX_PATH="/opt/rpitx"
ASSUME_YES=0
SKIP_RPITX=0
SKIP_NATIVE=0
SKIP_CERT=0
INSTALL_SERVICE=0

usage() {
  cat <<EOF
Usage: ./install.sh [options]

Options:
  --rpitx-path=PATH   where rpitx is/will be installed (default: $RPITX_PATH)
  --yes               assume "yes" for this script's own prompts
  --skip-rpitx        do not clone/install rpitx
  --skip-native       do not build native/webtx_iq or native/webtx-sendiq
  --skip-cert         do not generate a TLS certificate
  --install-service   install and enable the systemd service after setup
  -h, --help          show this help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --rpitx-path=*) RPITX_PATH="${arg#*=}" ;;
    --yes) ASSUME_YES=1 ;;
    --skip-rpitx) SKIP_RPITX=1 ;;
    --skip-native) SKIP_NATIVE=1 ;;
    --skip-cert) SKIP_CERT=1 ;;
    --install-service) INSTALL_SERVICE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown option: $arg" >&2; usage; exit 2 ;;
  esac
done

step() { printf '\n=== %s ===\n' "$1"; }

confirm() {
  if [ "$ASSUME_YES" = "1" ]; then return 0; fi
  read -r -p "$1 [y/N] " reply
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

step "1/5: System dependencies"
sudo apt-get update
sudo apt-get install -y python3 python3-pip build-essential git openssl \
  libraspberrypi-dev \
  python3-numpy python3-aiohttp python3-pytest

# aiohttp<3.9 lacks aiohttp.web.AppKey (webtx/server.py uses it); Ubuntu 22.04's
# apt package (python3-aiohttp) is only 3.8.1, so just checking that aiohttp
# imports is not enough - web.AppKey must be checked for explicitly.
if ! python3 -c "import numpy, pytest; from aiohttp import web; assert hasattr(web, 'AppKey')" >/dev/null 2>&1; then
  echo "install.sh: one or more apt packages were unavailable, or aiohttp is older than 3.9 (missing web.AppKey); installing/upgrading via pip instead."
  if ! pip3 install --break-system-packages numpy "aiohttp>=3.9" pytest 2>/dev/null; then
    pip3 install numpy "aiohttp>=3.9" pytest
  fi
fi
python3 -c "import numpy, aiohttp, pytest
from aiohttp import web
assert hasattr(web, 'AppKey'), 'aiohttp too old: missing web.AppKey (need aiohttp>=3.9)'
print('install.sh: numpy', numpy.__version__, 'aiohttp', aiohttp.__version__, 'pytest', pytest.__version__)"

step "2/5: native/webtx_iq + webtx-sendiq (see native/README.md)"
echo "install.sh: librpitx is vendored in this repository (vendor/librpitx) and"
echo "install.sh: builds automatically - no separate rpitx download is needed for this."
if [ "$SKIP_NATIVE" = "1" ]; then
  echo "install.sh: --skip-native given, not building native/webtx_iq or webtx-sendiq."
elif make -C native RPITX_PATH="$RPITX_PATH"; then
  echo "install.sh: built native/webtx_iq and native/webtx-sendiq successfully."
  if confirm "Install both to /usr/local/bin now?"; then
    sudo make -C native install
  fi
else
  echo "install.sh: native/webtx_iq and native/webtx-sendiq were not built (see above)."
  echo "install.sh: webtx will use stock sendiq or the null sink automatically -"
  echo "install.sh: see docs/LATENCY.md for the latency difference this makes."
fi

step "3/5: rpitx (upstream F5OEO/rpitx) - OPTIONAL"
echo "install.sh: not required for native/webtx_iq or native/webtx-sendiq (both"
echo "install.sh: build from vendor/ already, step 2). Only useful for rpitx's"
echo "install.sh: other, unrelated tools (pisstv, pocsag, ft8, ...)."
if [ "$SKIP_RPITX" = "1" ]; then
  echo "install.sh: --skip-rpitx given, not touching rpitx."
elif [ -x "$RPITX_PATH/sendiq" ]; then
  echo "install.sh: found an existing rpitx install at $RPITX_PATH, leaving it as-is."
elif confirm "Clone and install full upstream rpitx to $RPITX_PATH? (optional)"; then
  echo "install.sh: rpitx's own installer will ask whether to edit /boot/config.txt"
  echo "install.sh: (sets gpu_freq=250 for clock stability) - review that prompt yourself."
  sudo mkdir -p "$(dirname "$RPITX_PATH")"
  sudo git clone https://github.com/F5OEO/rpitx.git "$RPITX_PATH"
  (cd "$RPITX_PATH" && sudo ./install.sh)
else
  echo "install.sh: skipping rpitx (this is fine - neither native/webtx_iq nor"
  echo "install.sh: native/webtx-sendiq need it)."
fi

step "4/5: TLS certificate"
if [ "$SKIP_CERT" = "1" ]; then
  echo "install.sh: --skip-cert given, not generating a certificate."
else
  tools/gen-cert.sh certs
fi

step "5/5: Configuration"
if [ -f webtx.json ]; then
  echo "install.sh: webtx.json already exists, leaving it unchanged."
else
  cp webtx.example.json webtx.json
  sed -i "s#\"rpitx_path\": \"/opt/rpitx\"#\"rpitx_path\": \"$RPITX_PATH\"#" webtx.json
  echo "install.sh: created webtx.json (rpitx_path set to $RPITX_PATH)."
fi

if [ "$INSTALL_SERVICE" = "1" ]; then
  step "Installing systemd service"
  sed -e "s#__WEBTX_DIR__#$SCRIPT_DIR#g" systemd/webtx.service | sudo tee /etc/systemd/system/webtx.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now webtx.service
  echo "install.sh: service installed and started. Check with: sudo systemctl status webtx"
fi

step "Done"
cat <<EOF
Next steps:
  - Review webtx.json (frequency limits, sink, DSP settings).
  - Run manually:      sudo python3 -m webtx --config webtx.json
  - Or, if you used --install-service, it is already running:
                       sudo systemctl status webtx
  - Open:              https://<this-device-ip>:5000
    (accept the self-signed certificate warning once per browser)

See README.md for usage, troubleshooting, and latency tuning.
EOF
