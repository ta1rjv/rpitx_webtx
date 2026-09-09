#!/usr/bin/env bash
# Generates a self-signed TLS certificate for webtx.
#
# Browsers only grant microphone access (getUserMedia) on a "secure context":
# HTTPS, or http://localhost. Since webtx is normally reached over the LAN by
# IP address, it needs HTTPS, and there is no public CA for a private LAN
# address, so a self-signed certificate is the standard approach - the
# browser will show a one-time warning to accept it (see README.md).
set -euo pipefail

OUT_DIR="${1:-certs}"
CN="${2:-}"

if [ -z "$CN" ]; then
  CN="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [ -z "$CN" ]; then
    CN="localhost"
  fi
fi

mkdir -p "$OUT_DIR"

if [ -f "$OUT_DIR/cert.pem" ] && [ -f "$OUT_DIR/key.pem" ]; then
  echo "gen-cert: $OUT_DIR/cert.pem and key.pem already exist, leaving them in place."
  echo "gen-cert: delete them first if you want to regenerate."
  exit 0
fi

echo "gen-cert: generating a self-signed certificate for CN=$CN in $OUT_DIR/"
openssl req -x509 -newkey rsa:4096 \
  -keyout "$OUT_DIR/key.pem" -out "$OUT_DIR/cert.pem" \
  -days 3650 -nodes -subj "/CN=$CN"

chmod 600 "$OUT_DIR/key.pem"
echo "gen-cert: done. Point webtx.json's tls.cert/tls.key at these files (defaults already do)."
echo "gen-cert: if your Pi's IP address changes, re-run this script with the new address:"
echo "gen-cert:   rm -rf $OUT_DIR && tools/gen-cert.sh $OUT_DIR <new-ip>"
