# Buffett's $1 Test

> "Unrestricted earnings should be retained only when there is a reasonable
> prospect — backed preferably by historical evidence or, when appropriate,
> by a thoughtful analysis of the future — that for every dollar retained
> by the corporation, at least one dollar of market value will be created
> for owners."
>
> — **Warren Buffett, 1984 Letter to Shareholders**

## The formula

```
$1 Test = (Current Market Cap - Historical Market Cap)
        ÷ (Cumulative Retained Earnings over the same period)
```

If ratio ≥ 1 → management created at least $1 of value per $1 retained.
If ratio < 1 → management destroyed value. They should have paid it out
as dividends instead.

## Why it matters

Retained earnings are the easiest money for a CEO to destroy. They're already
inside the company. The CEO can:
- Spend them on empire-building acquisitions
- Bury them in vanity projects
- Keep cash earning 0% "for optionality"

The $1 test holds management accountable. If over 10 years they retained
$50B but only grew market cap by $30B, that's $20B of shareholder value
they torched. They should have paid it out.

## The asymmetry

Buffett holds a harder standard than most:
- **Good management**: $1 retained → $1.50-$2 market cap growth
- **Great management**: $1 → $3+
- **Capital destroyers**: $1 → $0.50

Over 20-30 years, the compounding effect of good capital allocation is
enormous. This is why Berkshire Hathaway's book value per share grew
at ~20% annualized for decades while the S&P did ~10%.

## Moatlens implementation

In Stage 4, we compute a **proxy** version: current market cap divided by
cumulative retained earnings over the available window (typically 5-10
years of data).

This is imperfect — a proper $1 test requires historical market cap data,
which we don't always have. The proxy answers: "Currently, how much market
cap exists per dollar the company has retained since going public?"

Use the result as a rough signal:
- **> 2.0**: strong capital allocation (management creating value)
- **1.0-2.0**: decent
- **< 1.0**: likely value destroyer
- **< 0.5**: management should be fired

## What to combine it with

The $1 test alone can deceive — a company with strong tailwinds grows
regardless of management skill. Combine with:
- Share count trend (are they buying back or diluting?)
- ROIC consistency (is retained capital earning high returns?)
- Buyback timing (buying at $200 when you'd buy yourself at $100?)
