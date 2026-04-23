#!/usr/bin/env python3
"""
Moatlens doctor — verify BYOK keys and provider connectivity.
Usage: python bin/doctor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.providers import (
    claude as p_claude,
)
from engine.providers import (
    fda as p_fda,
)
from engine.providers import (
    financial_datasets as p_fd,
)
from engine.providers import (
    finnhub as p_finnhub,
)
from engine.providers import (
    fred as p_fred,
)
from engine.providers import (
    marketaux as p_marketaux,
)
from engine.providers import (
    perplexity as p_pplx,
)
from engine.providers import (
    sec_api as p_sec,
)
from engine.providers import (
    yfinance_provider as p_yf,
)
from shared.config import load_config, load_keys_from_env


def main() -> int:
    load_config()  # loads .env into os.environ as a side effect
    keys = load_keys_from_env()

    print("=== Moatlens doctor ===\n")

    has_required, missing = keys.has_required()
    if missing:
        print(f"⚠️  Missing required keys: {', '.join(missing)}")

    checks = [
        ("yfinance (free)", lambda: p_yf.test_connection()),
        ("Financial Datasets", lambda: p_fd.test_connection(keys)),
        ("Perplexity", lambda: p_pplx.test_connection(keys)),
        ("Claude (Anthropic)", lambda: p_claude.test_connection(keys)),
        ("FRED (optional)", lambda: p_fred.test_connection(keys)),
        # v0.6 optional enrichment providers — skipped with ⚪ if key missing
        (
            "sec-api.io (optional)",
            lambda: p_sec.test_connection(keys)
            if keys.sec_api_io
            else (None, "key not set (SEC_API_IO_KEY)"),
        ),
        (
            "Finnhub (optional)",
            lambda: p_finnhub.test_connection(keys)
            if keys.finnhub
            else (None, "key not set (FINNHUB_API_KEY)"),
        ),
        (
            "MarketAux (optional)",
            lambda: p_marketaux.test_connection(keys)
            if keys.marketaux
            else (None, "key not set (MARKETAUX_API_KEY)"),
        ),
        ("FDA / ClinicalTrials (free)", lambda: p_fda.test_connection(keys)),
    ]

    ok_count = 0
    required_fail = False
    skipped = 0
    for name, fn in checks:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"exception: {e}"
        if ok is None:
            icon = "⚪"
            skipped += 1
        elif ok:
            icon = "✅"
            ok_count += 1
        else:
            icon = "❌"
            if "optional" not in name and "free" not in name:
                required_fail = True
        print(f"  {icon} {name}: {msg}")

    total_run = len(checks) - skipped
    print(
        f"\nResult: {ok_count}/{total_run} passed"
        + (f"  ({skipped} skipped — no key)" if skipped else "")
    )
    return 1 if required_fail else 0


if __name__ == "__main__":
    sys.exit(main())
