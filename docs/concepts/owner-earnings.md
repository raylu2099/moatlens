# Owner Earnings

> "If we think through these questions, we can gain some insights about what may be called 'owner earnings.' These represent (a) reported earnings plus (b) depreciation, depletion, amortization, and certain other non-cash charges such as Company N's item (1) less (c) the average annual amount of capitalized expenditures for plant and equipment, etc. that the business requires to fully maintain its long-term competitive position and its unit volume."
>
> — **Warren Buffett, 1986 Letter to Shareholders**

## The formula

```
Owner Earnings = Net Income
              + Depreciation & Amortization
              ± Other non-cash items
              - Maintenance Capital Expenditure
```

For technology companies, Moatlens adds one more adjustment per modern Buffett
practice:

```
              - Stock-Based Compensation (SBC)
```

Why? SBC is real economic cost — it dilutes the shareholder. When a tech company
reports "GAAP net loss but adjusted profit ex-SBC", that's usually a red flag.
Buffett explicitly called this out in his 2019 letter about tech accounting.

## Why not EPS?

EPS is an accounting construct. It includes:
- Depreciation of old assets the company may never replace at the stated rate
- Non-cash charges that can be manipulated
- One-time items that flatter or depress the number

Owner Earnings answers: **"If I owned this company outright, how much cash
could I take home each year without impairing the business?"**

## Maintenance vs growth capex

Moatlens approximates maintenance capex as `min(total capex, D&A)`. This is
conservative — if a company spends less than D&A on capex, we assume they're
undermaintaining (Munger's "eating the seed corn" concern).

For capital-light businesses (software, franchising), maintenance capex is
much lower than D&A, and Owner Earnings can exceed Net Income significantly.
That's the Buffett sweet spot.

## Example: classic vs tech

**Classic consumer brand** (e.g. Coca-Cola):
- NI $10B + D&A $1B − maintenance capex $1B − SBC $0.2B = **Owner Earnings ~$9.8B**
- Very close to Net Income → high-quality earnings

**Mature tech giant** (e.g. Alphabet):
- NI $80B + D&A $13B − maintenance capex $25B − SBC $22B = **Owner Earnings ~$46B**
- Large gap from NI due to heavy SBC → earnings quality is lower than it looks

## Moatlens usage

Stage 5 of the audit computes this per-company, with `--tech` flag enabling
SBC subtraction. The FCF Margin we target is `Owner Earnings / Revenue ≥ 15%`.

Margins above 20% are rare and indicate pricing power + capital efficiency —
the Buffett "wonderful business" sweet spot.
