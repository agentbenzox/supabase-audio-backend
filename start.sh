#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status.
set -e

# Run Gunicorn
exec /home/appuser/venv/bin/gunicorn -w 4 'app:app' -b 0.0.0.0:$PORT
