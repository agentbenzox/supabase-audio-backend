#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status.
set -e

# Run Gunicorn
exec gunicorn --bind 0.0.0.0:$PORT app:app
