#!/usr/bin/env bash
# CareLoop helper. One command for every routine task, so you never retype
# flags or fight the Cloud Shell 403 again. Run it from anywhere.
#
#   ./run.sh web            start the dev UI (CORS handled, no 403)
#   ./run.sh chat           talk to the agent in the terminal (no browser)
#   ./run.sh ingest anita   build or refresh a patient's ledger
#   ./run.sh test           run the test suite
#   ./run.sh check          show your setup and sanity-check it

# Always work from the repo, whatever directory you launch from.
cd "$HOME/triagemate-gcp" 2>/dev/null || { echo "Can't find ~/triagemate-gcp"; exit 2; }

# Load careloop/.env into the environment so plain python commands see the
# same GOOGLE_API_KEY / CARELOOP_STORE / model as adk does. (A bare
# `python scripts/ingest.py` does NOT read .env on its own -- this fixes that.)
if [ -f careloop/.env ]; then
  set -a; source careloop/.env 2>/dev/null; set +a
fi

# Activate the virtualenv if present.
[ -f .venv/bin/activate ] && source .venv/bin/activate

CMD="${1:-help}"
case "$CMD" in
  web)
    PORT="${2:-8080}"
    echo "Dev UI on port $PORT (CORS allowed). Open Web Preview -> port $PORT."
    exec adk web --port "$PORT" --allow_origins="*"
    ;;
  chat)
    exec adk run careloop
    ;;
  ingest)
    PID="${2:-anita}"
    NAME="${3:-$PID}"
    exec python scripts/ingest.py --docs scripts/sample_docs --patient "$PID" --name "$NAME" --mock
    ;;
  test)
    exec python -m pytest tests/ -v
    ;;
  check)
    echo "--------------------------------------------------"
    echo "Repo:    $(pwd)"
    echo "Code:    $(grep -q 'Store:' scripts/ingest.py && echo 'UP TO DATE (Firestore-ready)' || echo 'OLD -- ingest.py needs updating')"
    echo "Store:   ${CARELOOP_STORE:-local (default)}"
    echo "Model:   ${CARELOOP_MODEL:-not set}"
    echo "Vertex:  ${GOOGLE_GENAI_USE_VERTEXAI:-not set}"
    echo "API key: $([ -n "$GOOGLE_API_KEY" ] && echo 'set' || echo 'not set')"
    echo -n "Ledgers: "; ls ledgers/ 2>/dev/null | tr '\n' ' ' || echo -n "(none yet)"; echo
    echo "--------------------------------------------------"
    ;;
  *)
    echo "Usage: ./run.sh {web | chat | ingest <patient> | test | check}"
    ;;
esac
