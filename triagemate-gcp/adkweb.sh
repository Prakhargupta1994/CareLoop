#!/usr/bin/env bash
#
# Launch the ADK dev UI so Cloud Shell's Web Preview stops throwing 403s.
#
# Why this exists: the 403 on every JavaScript file is a CORS block. Through
# Cloud Shell's proxy the browser's origin is the *.cloudshell.dev preview
# host, not localhost, so `adk web` rejects the module scripts unless we
# allow that origin. This wrapper ALWAYS passes --allow_origins, and ALWAYS
# runs from the repo root (so ADK finds the careloop agent). Use it instead
# of `adk web`.
#
# Usage:
#   ./adkweb.sh          # port 8080 (default)
#   ./adkweb.sh 8000     # a different port
#   bash adkweb.sh       # if the file is not marked executable
#
# Then open Cloud Shell's Web Preview -> Preview on that port.

# Always operate from the folder this script lives in (the repo root),
# whatever directory you launch it from.
cd "$(dirname "$0")" || exit 1

# Activate the local virtualenv if there is one.
[ -f .venv/bin/activate ] && source .venv/bin/activate

PORT="${1:-8080}"

echo "-------------------------------------------------------------"
echo " ADK dev UI starting on port ${PORT} with CORS allowed."
echo " Open Cloud Shell Web Preview -> Preview on port ${PORT}."
echo "-------------------------------------------------------------"

# --allow_origins="*" clears the Cloud Shell proxy 403s. If your setup ever
# rejects the wildcard, replace the line below with the regex form:
#   exec adk web --port "${PORT}" --allow_origins="regex:https://.*\.cloudshell\.dev"
exec adk web --port "${PORT}" --allow_origins="*"
