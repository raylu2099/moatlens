# Inversion — Munger's Second Superpower

> "Invert, always invert. Many hard problems are best solved when they
> are addressed backward."
>
> — **Charlie Munger, quoting Carl Jacobi**

## The core technique

Most investors spend 95% of their time asking: **"How will this succeed?"**

Munger says flip it: spend 50% of your time asking **"How will this fail?"**

The reason: avoiding stupidity has higher long-term ROI than seeking
brilliance. You don't need to be right about the upside — you need to
be not-catastrophically-wrong about the downside.

## Why it works

Three reasons:

1. **Asymmetry of outcomes.** In investing, a 50% loss requires a 100%
   gain to recover. A 90% loss requires a 900% gain. Downside protection
   compounds your ability to stay in the game.

2. **Behavioral bias.** Humans are systematically optimistic about
   investments they already like. Inversion forces you to overcome
   confirmation bias.

3. **Better research.** Answering "how could this fail" forces specific,
   testable scenarios — not vague optimism. It creates falsifiable
   hypotheses you can track.

## How Moatlens implements it

In **Stage 8**, the audit asks Claude to generate 3-5 specific failure
modes for the investment. Each must include:

- **Scenario**: concrete description (not "management changes" but
  "Jensen Huang steps down as CEO in the next 3 years and the successor
  loses the architectural vision that built CUDA")
- **Probability**: 0-100% (force yourself to pin a number)
- **Early signals**: what would you see first if this is happening?
- **Impact on thesis**: fatal / partial / minor

Then it asks you to think about whether the cumulative failure probability
(sum of above) is <50%. If not, you shouldn't invest.

## The Variant View Canvas

Coupled with inversion, Moatlens asks Howard Marks' 9 questions:

1. What's the range of outcomes (worst / base / best)?
2. What do you think is most likely?
3. What's your probability of being correct?
4. What's the market's consensus?
5. How does your view differ?
6. Which scenario does the current price reflect?
7. Is price sentiment optimistic, pessimistic, or neutral?
8. If the market is right, how will price change?
9. If you're right, how will price change?

Together these force a rigorous "what do I know that the market doesn't?"
— the essence of Howard Marks' famous "**Correct × Non-consensus**"
definition of alpha.

## Applying inversion in real life

Even outside Moatlens, use inversion every time you're about to buy:

- **"What would the seller know that I don't?"** (information asymmetry)
- **"What would I need to believe for this to work?"** (premise audit)
- **"If I wake up in 5 years and this was a disaster, what caused it?"**
  (premortem thinking)
- **"What would Munger laugh at me for?"** (external perspective)

The goal isn't to talk yourself out of every investment. The goal is to
**know what you're betting on**, specifically, so you can recognize when
the thesis breaks.

## Munger's related principle: avoid stupidity

Related to inversion is Munger's insight that **avoiding stupidity is
more important than seeking brilliance**. Why?

Because the downside of a stupid decision is often catastrophic (bankruptcy,
divorce, jail), while the upside of a brilliant one is often limited
(you already have most of what you need). Asymmetric risk means asymmetric
process — spend disproportionate time on what could go wrong.

## Bottom line

Every Moatlens audit Stage 8 asks you: **How could this fail?** If you
can't answer that question with 3 specific scenarios, you don't understand
the investment well enough to own it.
