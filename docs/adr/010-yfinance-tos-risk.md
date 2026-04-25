# ADR 010 — yfinance ToS gray area: self-use only, not SaaS

**Status:** Accepted
**Date:** 2026-04-25
**Decision owner:** Ray

## Context

Moatlens calls `yfinance` in `engine/providers/yfinance_provider.py` for:
- Current price (`fetch_current_price`)
- Trailing / forward P/E, market cap, beta, shares outstanding (`fetch_multiples`)
- Sector / industry metadata (`fetch_company_info`)
- Historical price series (`fetch_history`)

`yfinance` is a popular open-source Python wrapper around Yahoo Finance's
internal APIs. The package itself is MIT-licensed, but the Yahoo endpoints it
hits are governed by Yahoo's own ToS — which prohibits "use for any commercial
use" (Yahoo Terms of Service §4). The upstream maintainer (@ranaroussi) states
in the yfinance README that the library is intended for "research and educational
purposes" and users "should refer to Yahoo!'s terms of use for details on your
rights to use the actual data downloaded."

Practical observations:
- The endpoints have rate limits that Yahoo occasionally tightens without notice
  (this has broken real projects in 2022 and 2024).
- No documented SLA; responses change shape periodically (e.g. fast_info vs info
  dicts; ticker symbol format changes).
- No legal precedent on Yahoo pursuing individual hobbyist users, but several
  cease-and-desist letters to for-profit scrapers are on public record.

## Decision

Moatlens uses `yfinance` **exclusively for Ray's single-user, personal research**.
If the three-month self-evaluation (see CLAUDE.md bottom) on 2026-07-18 turns
"yes" on all three questions and the migration path in `docs/migration/v1-path.md`
becomes active, yfinance **must be replaced or licensed before any multi-user
deployment**. Specifically:

1. Any SaaS / shared-instance deployment replaces yfinance with a licensed data
   provider (financial-datasets.ai already covers fundamentals; candidates for
   prices: IEX Cloud, Alpaca, Polygon, Tiingo).
2. Monte Carlo / DCF logic in s6 does not become dependent on yfinance-only
   fields — the valuation layer should work with any provider that surfaces
   (price, shares_outstanding, beta, market_cap).
3. No Moatlens endpoint exposes raw yfinance responses to a third party (not
   even caches / snapshots in audit reports). Derived numbers are fine;
   responses wholesale are not.

## Consequences

- **Personal use:** fine as-is. Single-user, LAN/Tailscale-only, no
  redistribution of Yahoo data.
- **Any external sharing:** violates the spirit (and likely letter) of Yahoo's
  ToS. Before the v1 migration triggers, this provider needs a replacement
  plan, not a retrofit scramble.
- **Resilience:** the wrapper can break on Yahoo changes. `bin/doctor.py`
  covers this — when yfinance failures show up, treat as "provider flake,
  retry" unless the failure mode is structural (e.g. `info` dict shape change).
- **Code locality:** all yfinance calls funnel through
  `engine/providers/yfinance_provider.py`. A future migration is one
  provider-module rewrite, not a grep-and-replace sweep.

## Alternatives considered

- **Pay for a commercial price feed now**: rejected. ~$50-200/mo for APIs we
  use for one user who audits 3-5 tickers/week is overkill. Reconsider if
  v1 triggers.
- **Drop real-time price entirely**: rejected. Current price gates the
  buy-zone / sell-zone banner on `/portfolio` and the "需要重审视" signal —
  both are core UX, not decorative.
- **Switch to financial-datasets.ai /prices/snapshot**: partially yes for
  fundamentals; their snapshot endpoint exists but beta / market_cap /
  sector coverage is uneven across international tickers. yfinance stays
  for the gap.

## References

- `engine/providers/yfinance_provider.py` — the whole concentration point
- `bin/doctor.py` — health check that surfaces yfinance flakiness
- `docs/migration/v1-path.md` — what to do if this ADR needs revisiting
- Yahoo ToS: https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html
