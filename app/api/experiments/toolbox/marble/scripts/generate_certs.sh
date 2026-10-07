#!/usr/bin/env bash
# Generates a self-signed TLS cert/key for the local Ollama TLS-terminating
# proxy (scripts/tls_ollama_proxy.py), so that agent<->LLM traffic on
# 127.0.0.1 is genuinely encrypted and worth capturing. Safe to re-run --
# skips generation if a cert already exists.
set -euo pipefail

CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/certs"
mkdir -p "$CERT_DIR"

if [[ -f "$CERT_DIR/cert.pem" && -f "$CERT_DIR/key.pem" ]]; then
    echo "certs already exist at $CERT_DIR, skipping"
    exit 0
fi

openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -days 3650 \
    -subj "/CN=127.0.0.1" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo "generated self-signed cert at $CERT_DIR/{cert,key}.pem"
