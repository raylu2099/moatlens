#!/bin/bash
# Moatlens setup — creates venv, installs deps, initializes DB.
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "=== Moatlens setup ==="
echo "Project dir: $PROJECT_DIR"

# Python detection
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    for cand in python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" >/dev/null 2>&1; then
            ver=$("$cand" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                PYTHON="$cand"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10+ required. Install and retry." >&2
    exit 1
fi

echo "Using: $PYTHON ($("$PYTHON" --version))"

# venv
if [ ! -d .venv ]; then
    "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
echo "Dependencies installed."

# .env
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "Created .env — edit it with your BYOK keys."
fi

mkdir -p data/cache data/users logs
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys (ANTHROPIC, PERPLEXITY, FINANCIAL_DATASETS, FRED)"
echo "  2. Test: python bin/doctor.py"
echo "  3. CLI:  python -m cli audit AAPL"
echo "  4. Web:  uvicorn web.main:app --reload --port 8000"
echo "  5. Docker: docker compose up"
