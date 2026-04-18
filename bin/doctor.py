#!/usr/bin/env python3
"""
Moatlens doctor — verify BYOK keys and provider connectivity.
Usage: python bin/doctor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import load_config, load_keys_from_env
from engine.providers import (
    claude as p_claude,
    fred as p_fred,
    financial_datasets as p_fd,
    perplexity as p_pplx,
    yfinance_provider as p_yf,
)


def main() -> int:
    cfg = load_config()
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
    ]

    ok_count = 0
    required_fail = False
    for name, fn in checks:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"exception: {e}"
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {msg}")
        if ok:
            ok_count += 1
        elif "optional" not in name:
            required_fail = True

    print(f"\nResult: {ok_count}/{len(checks)} passed")
    return 1 if required_fail else 0


if __name__ == "__main__":
    sys.exit(main())
