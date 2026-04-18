# Margin of Safety

> "In the old legend the wise men finally boiled down the history of
> mortal affairs into the single phrase, 'This too will pass.' Confronted
> with a like challenge to distill the secret of sound investment into
> three words, we venture the motto, MARGIN OF SAFETY."
>
> — **Benjamin Graham, The Intelligent Investor (1973 edition)**

## The principle

You never know exactly what a company is worth. Your estimate could be
off by 20-30% in either direction. So don't buy when price equals your
estimate — buy when price is **well below** your estimate, so you're
protected if you're wrong.

## The math

```
Margin of Safety (%) = (Intrinsic Value - Current Price) / Intrinsic Value × 100
```

Moatlens rule of thumb (from Buffett's practice):

- **≥ 50% discount**: aggressive buying — double-sized position
- **30-50% discount**: standard buy zone
- **10-30% discount**: acceptable entry for extremely high-quality business
- **0-10% discount**: neutral zone, wait
- **< 0% (premium)**: only if exceptional tailwinds + your conviction is extreme

## Why 30% and not 10%?

Three reasons to demand a bigger buffer than you think:

1. **Estimation error.** Your DCF assumes future FCF growth. If you're
   wrong by 2% annualized, after 10 years that's a 20-25% error in
   terminal value.

2. **Unknown unknowns.** Black swans, regime shifts, disruption you
   didn't anticipate. History shows these happen every 3-7 years.

3. **Opportunity cost.** Your capital is scarce. Every dollar committed
   at fair value is a dollar not available when a true bargain appears.

## Graham vs Buffett vs Marks

**Graham**: look for companies trading below liquidation value (net-net).
30-70% below book value was common in the 1930s-1950s. Today mostly
extinct except in deep value small caps.

**Buffett (evolved)**: quality matters more than price. A wonderful
company at 80% of fair value beats a mediocre one at 50%. The moat
**creates** the margin of safety.

**Howard Marks**: focus on **asymmetric** return profiles. Even if
there's limited discount to intrinsic, if the downside is truly capped
and upside is multiple-bagger, the bet can work (credit plays, distressed).

Moatlens blends these: Stage 7 explicitly computes margin of safety
**and** asymmetry (upside/downside ratio), so you can choose which
framework fits this specific investment.

## What happens in Stage 7

1. Takes base-case intrinsic value from Stage 6 DCF.
2. Computes:
   - Target buy price = IV × 0.7 (30% discount)
   - Target aggressive buy = IV × 0.5 (50% discount)
   - Target sell price = IV × 1.1 (10% premium)
3. Shows current discount/premium.
4. Computes upside to bull-case IV and downside to bear-case IV.
5. Computes asymmetry ratio = upside / downside.
6. Runs half-Kelly sizing to suggest position size.

## Common mistakes

**Mistake 1: Anchor to recent price, not intrinsic value.**
"It was $100 last month, now $70 — such a discount!" No. The price
wasn't the anchor. Your *calculation* of intrinsic value is. Recompute
after every major piece of news.

**Mistake 2: Use a lower discount because you're "confident".**
Overconfidence is the most expensive bias in investing. If you think
you deserve only a 10% discount because you've studied this company
for 5 years, you're probably about to be humbled. Stick with ≥30%.

**Mistake 3: Give up on margin of safety for "compounders".**
A common 2020s pitch: "Don't worry about price, this compounds at 20%."
No. Even compounders can experience 50% drawdowns. Margin of safety
prevents you from buying at the top of that drawdown.

## The Buffett rule of waiting

"Our favorite holding period is forever" — but "our favorite **buying**
period is when others are panicking."

Margin of safety means: most of the time, you should **not** be buying.
You should be waiting. When the right price comes — 30%+ below your
calculated value — you buy aggressively.

Moatlens embraces this discomfort. Most audits will end with "current
price is above buy target — add to watchlist, revisit quarterly."

That's correct. That's value investing.
