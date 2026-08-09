#!/bin/bash

set -euo pipefail

cd -- "$(dirname -- "$0")"

show_startup_error() {
  local exit_code=$?
  trap - ERR
  echo
  echo "Sari could not start. Review the error above, then run:"
  echo "  docker compose ps"
  echo "  docker compose logs --tail=100 frontend backend ocr-gateway database"
  echo
  read -r -p "Press Enter to close..."
  exit "$exit_code"
}

trap show_startup_error ERR

if [[ ! -f .env ]]; then
  echo "Cannot start Sari: the project-root .env file is missing."
  echo "Create it from .env.example, then replace the password and token placeholders."
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Cannot start Sari: Docker is not installed or is not available in PATH."
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Cannot start Sari: Docker Desktop is not running."
  echo "Open Docker Desktop, wait until it is ready, then double-click this file again."
  read -r -p "Press Enter to close..."
  exit 1
fi

echo "Building and starting the complete local Sari stack..."
docker compose up -d --build --wait

echo
echo "Sari is ready."
echo "Application: http://127.0.0.1:8080"
echo "API, OCR, and PostgreSQL: private Docker network only"
echo
read -r -p "Press Enter to close this window..."
