"""
test_insights.py — grounded-visuals builder (spec 2026-10-03-report-insights-visuals-design).

Fixtures are excerpts copied from real stored reports (MARA 2026-10-03, legacy NIO,
VDY, CLOV) so parser tests pin the producer's actual table formats.
"""

from __future__ import annotations

import pytest

from src import insights

MARA_OPTIONS = """# Options Analysis: MARA — MARA Holdings Inc

**Generated:** 2026-10-03 13:11 EDT
**Current Price:** $11.23 USD | **Market Cap:** ~$2.1B

---
## Expected Move

| Timeframe | Expected Move ($) | Expected Move (%) | Range |
|-----------|------------------|--------------------|-------|
| Next Week | +/- $2.35 | +/- 20.9% | $8.88 — $13.58 |
| Next Month | +/- $4.80 | +/- 42.7% | $6.43 — $16.03 |
| Next 90 Days | +/- $7.20 | +/- 64.1% | $4.03 — $18.43 |

---
## Recommended Strategies

### Strategy 1: Collar — RECOMMENDED (HEDGE)

| Leg | Action | Strike | Expiration | Type | Price |
|-----|--------|--------|------------|------|-------|
| 1 | Buy | $10.00 | Nov 21, 2026 | Put | ~$1.55 |
| 2 | Sell | $13.00 | Nov 21, 2026 | Call | ~$1.35 |

| Metric | Value |
|--------|-------|
| Net Cost | ~$0.20/share |

---

### Strategy 3: Bear Put Spread (DEFINED RISK HEDGE)
| Leg | Action | Strike | Expiry | Type | Price |
|-----|--------|--------|--------|------|-------|
| 1 | Buy | $11.00 | Nov 21 | Put | ~$2.20 |
| 2 | Sell | $8.00 | Nov 21 | Put | ~$0.80 |

---
## Key Levels for Options Traders
| Level | Price | Significance |
|-------|-------|-------------|
| Max Pain (Oct) | $10.00 | Options market equilibrium |
| 52-Week High | $23.45 | Major resistance |
| 52-Week Low | $6.66 | Key support level |
| Expected Move High | $16.03 | 1-sigma upside |
| Expected Move Low | $6.43 | 1-sigma downside |
| Technical Support | $9.00 | Prior base |
"""

NIO_LEGACY = """# Options Analysis: NIO

**Current Price:** $4.88

## Expected Move

| Timeframe | Expected Move ($) | Expected Move (%) | Range |
|-----------|------------------|--------------------|-------|
| Next Week (7 days) | +/- $0.39 | +/- 8.0% | $4.49 — $5.27 |
| Next Month (30 days) | +/- $0.81 | +/- 16.6% | $4.07 — $5.69 |
| Into Earnings (61 days) | +/- $1.16 | +/- 23.7% | $3.72 — $6.04 |
| Next 90 Days | +/- $1.41 | +/- 28.8% | $3.47 — $6.29 |

| Quarter | Implied Move | Actual Move | Beat/Miss | Direction |
|---------|-------------|-------------|-----------|-----------|
| Q1 2026 (May 21) | ~+/- 18% | ~-9% | Deliveries beat | Down |

## Recommended Strategies

### Strategy 1: Collar — $5.00 Call / $4.50 Put (Aug 15) — RECOMMENDED ✦ HEDGE

| Leg | Action | Strike | Expiration | Type | Est. Price |
|-----|--------|--------|------------|------|-----------|
| 1 | Sell | $5.00 | Aug 15, 2026 | Call | +$0.31 |
| 2 | Buy | $4.50 | Aug 15, 2026 | Put | -$0.18 |
| — | — | Net Credit | — | — | **+$0.14/share** |

## Key Levels for Options Traders

| Level | Price | Significance |
|-------|-------|-------------|
| Max Pain (Jul 18, est.) | ~$5.00 | Options market equilibrium — mild gravitational pull |
| Call Wall (est.) | ~$5.50–$6.00 | Heavy call OI creates resistance |
| Put Wall (est.) | ~$4.00 | Elevated put OI provides some support |
| Expected Move High (1 month) | $5.69 | 1-sigma upside |
| Expected Move Low (1 month) | $4.07 | 1-sigma downside |
| 52-Week Low | $3.38 | Catastrophic support; structural floor |
| Technical Resistance | $5.40 / $5.74–$5.84 | Chart-based resistance zones |
| Current Price | $4.88 | Just below the $4.89 support cluster |
"""

CLOV_PMCC = """**Current Price:** $4.38

## Recommended Strategies

### Strategy 1: Poor Man's Covered Call (PMCC) — RECOMMENDED (INCOME)

| Leg | Action | Strike | Expiration | Type | Price |
|-----|--------|--------|------------|------|-------|
| 1 (Anchor) | Buy | $3.00 | Jan 16, 2027 | Call | ~$1.65 |
| 2 (Income) | Sell | $5.00 | Oct 17, 2026 | Call | ~$0.28 |
"""

VDY_OPTIONS = """# Options Analysis: VDY — Vanguard FTSE Canadian High Dividend Yield ETF

**Current Price:** CAD $75.75 | **AUM:** ~CAD $7B+

## Options Availability Assessment

**VDY.TO does not have a liquid listed options market.**
"""


class TestReportText:
    def test_report_text_undoes_window_overlap(self) -> None:
        # Mirror trade_memory._chunk_by_section: 1500-char windows, 100-char overlap.
        head = "# Title\n\n**Current Price:** $11.23"
        long_section = "## Recommended Strategies\n" + "".join(f"| {i} | Buy | $1{i % 10}.00 |\n" for i in range(120))
        tail = "## Key Levels\n| Level | Price |"
        windows = [long_section[s:s + 1500] for s in range(0, len(long_section), 1400)]
        chunks = [{"text": head, "metadata": {"section": "preamble"}}]
        chunks += [{"text": w, "metadata": {"section": "recommended-strategies"}} for w in windows]
        chunks += [{"text": tail, "metadata": {"section": "key-levels"}}]
        assert len(windows) > 1
        assert insights.report_text(chunks) == "\n".join([head, long_section, tail])

    def test_report_text_keeps_short_same_slug_sections(self) -> None:
        chunks = [
            {"text": "## Notes\nfirst", "metadata": {"section": "notes"}},
            {"text": "## Notes\nsecond", "metadata": {"section": "notes"}},
        ]
        assert insights.report_text(chunks) == "## Notes\nfirst\n## Notes\nsecond"


class TestCurrentPrice:
    def test_current_price_from_report_text(self) -> None:
        assert insights.parse_current_price(MARA_OPTIONS) == 11.23
        assert insights.parse_current_price(NIO_LEGACY) == 4.88

    def test_current_price_with_currency_code(self) -> None:
        assert insights.parse_current_price(VDY_OPTIONS) == 75.75

    def test_current_price_missing(self) -> None:
        assert insights.parse_current_price("no price here") is None


class TestExpectedMove:
    def test_expected_move_mara(self) -> None:
        em = insights.parse_expected_move(MARA_OPTIONS, 11.23)
        assert em["price"] == 11.23
        assert em["ranges"][0] == {
            "label": "Next Week", "low": 8.88, "high": 13.58, "pct": 20.9, "approx": False,
        }
        assert [r["label"] for r in em["ranges"]] == ["Next Week", "Next Month", "Next 90 Days"]

    def test_expected_move_ignores_other_tables(self) -> None:
        em = insights.parse_expected_move(NIO_LEGACY, 4.88)
        assert [r["label"] for r in em["ranges"]] == [
            "Next Week (7 days)", "Next Month (30 days)", "Into Earnings (61 days)", "Next 90 Days",
        ]

    def test_expected_move_missing(self) -> None:
        assert insights.parse_expected_move(VDY_OPTIONS, 75.75) is None


class TestKeyLevels:
    def test_key_levels_sorted_high_to_low(self) -> None:
        kl = insights.parse_key_levels(MARA_OPTIONS, 11.23)
        assert [lv["price"] for lv in kl["levels"]] == [23.45, 16.03, 10.0, 9.0, 6.66, 6.43]
        assert kl["levels"][2] == {
            "label": "Max Pain (Oct)", "price": 10.0, "note": "Options market equilibrium", "approx": False,
        }

    def test_key_levels_drop_ranges_and_current_row(self) -> None:
        kl = insights.parse_key_levels(NIO_LEGACY, 4.88)
        labels = [lv["label"] for lv in kl["levels"]]
        assert "Call Wall (est.)" not in labels
        assert "Technical Resistance" not in labels
        assert "Current Price" not in labels
        assert [lv["price"] for lv in kl["levels"]] == [5.69, 5.0, 4.07, 4.0, 3.38]
        assert kl["levels"][1]["approx"] is True

    def test_key_levels_drop_implausible_prices(self) -> None:
        text = "| Level | Price | Significance |\n|---|---|---|\n| Typo | $1123.00 | x |\n| Support | $10.00 | y |"
        kl = insights.parse_key_levels(text, 11.23)
        assert [lv["price"] for lv in kl["levels"]] == [10.0]

    def test_key_levels_missing(self) -> None:
        assert insights.parse_key_levels(VDY_OPTIONS, 75.75) is None


def _leg(action: str, kind: str, strike: float, premium: float) -> dict:
    return {"action": action, "type": kind, "strike": strike, "premium": premium, "approx": False}


class TestPayoff:
    def test_collar_reference_values(self) -> None:
        # Spec §5 reference: MARA collar 2026-10-03.
        p = insights.payoff([_leg("buy", "put", 10.0, 1.55), _leg("sell", "call", 13.0, 1.35)], 11.23, True)
        assert p["max_loss"] == -1.43
        assert p["max_gain"] == 1.57
        assert p["breakevens"] == [11.43]

    def test_bear_put_spread_without_stock(self) -> None:
        p = insights.payoff([_leg("buy", "put", 11.0, 2.20), _leg("sell", "put", 8.0, 0.80)], 11.23, False)
        assert (p["max_gain"], p["max_loss"], p["breakevens"]) == (1.6, -1.4, [9.6])

    def test_covered_call(self) -> None:
        p = insights.payoff([_leg("sell", "call", 5.50, 0.30)], 5.10, True)
        assert (p["max_gain"], p["max_loss"], p["breakevens"]) == (0.7, -4.8, [4.8])

    def test_unbounded_sides(self) -> None:
        assert insights.payoff([_leg("buy", "call", 10.0, 1.0)], 10.0, False)["max_gain"] is None
        assert insights.payoff([_leg("sell", "call", 10.0, 1.0)], 10.0, False)["max_loss"] is None

    def test_curve_is_bounded_and_covers_price(self) -> None:
        p = insights.payoff([_leg("buy", "put", 10.0, 1.55), _leg("sell", "call", 13.0, 1.35)], 11.23, True)
        xs = [x for x, _ in p["curve"]]
        assert len(p["curve"]) <= 80
        assert xs == sorted(xs) and xs[0] < 10.0 and xs[-1] > 13.0
        assert [10.0, -1.43] in p["curve"] and [13.0, 1.57] in p["curve"]


class TestStrategy:
    def test_strategy_mara_collar(self) -> None:
        s = insights.parse_strategy(MARA_OPTIONS, 11.23)
        assert s["name"] == "Collar"
        assert s["expiration"] == "Nov 21, 2026"
        assert s["includes_stock"] is True
        assert s["legs"] == [
            {"action": "buy", "type": "put", "strike": 10.0, "premium": 1.55, "approx": True},
            {"action": "sell", "type": "call", "strike": 13.0, "premium": 1.35, "approx": True},
        ]
        assert (s["max_loss"], s["max_gain"], s["breakevens"]) == (-1.43, 1.57, [11.43])

    def test_strategy_nio_signed_premiums_and_summary_row(self) -> None:
        s = insights.parse_strategy(NIO_LEGACY, 4.88)
        assert s["name"] == "Collar"
        assert [(leg["action"], leg["premium"]) for leg in s["legs"]] == [("sell", 0.31), ("buy", 0.18)]
        assert (s["max_loss"], s["max_gain"], s["breakevens"]) == (-0.25, 0.25, [4.75])

    def test_strategy_expiry_and_est_price_headers(self) -> None:
        text = (
            "### Strategy 1: Bear Put Spread — HEDGE\n\n"
            "| Leg | Action | Strike | Expiry | Type | Price (est.) |\n"
            "|---|---|---|---|---|---|\n"
            "| 1 | Buy | $11.00 | Nov 21 | Put | ~$2.20 |\n"
            "| 2 | Sell | $8.00 | Nov 21 | Put | ~$0.80 |\n"
        )
        s = insights.parse_strategy(text, 11.23)
        assert s["includes_stock"] is False
        assert (s["max_gain"], s["max_loss"]) == (1.6, -1.4)

    def test_strategy_pmcc_mixed_expirations_is_none(self) -> None:
        assert insights.parse_strategy(CLOV_PMCC, 4.38) is None

    def test_strategy_only_reads_strategy_1_section(self) -> None:
        text = (
            "### Strategy 1: Collar — HEDGE\n\nNo legs table here.\n\n"
            "### Strategy 2: Bear Put Spread\n"
            "| Leg | Action | Strike | Expiration | Type | Price |\n|---|---|---|---|---|---|\n"
            "| 1 | Buy | $11.00 | Nov 21 | Put | $2.20 |\n"
        )
        assert insights.parse_strategy(text, 11.23) is None

    def test_strategy_missing(self) -> None:
        assert insights.parse_strategy(VDY_OPTIONS, 75.75) is None
