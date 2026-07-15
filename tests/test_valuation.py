from app.valuation import DcfInputs, build_valuation, dcf_fair_value, verdict


def base_inputs(**overrides):
    inputs = dict(
        base_fcf=100_000_000,
        growth=0.10,
        terminal_growth=0.025,
        discount_rate=0.09,
        shares_outstanding=50_000_000,
    )
    inputs.update(overrides)
    return DcfInputs(**inputs)


def test_dcf_produces_positive_per_share_value():
    fv = dcf_fair_value(base_inputs())
    assert fv is not None
    assert fv > 0
    # 100M FCF / 50M shares = $2/share of trailing FCF; a ~9% discount rate
    # and fading 10% growth should value that in the tens of dollars.
    assert 20 < fv < 100


def test_higher_growth_means_higher_fair_value():
    low = dcf_fair_value(base_inputs(growth=0.02))
    high = dcf_fair_value(base_inputs(growth=0.20))
    assert high > low


def test_higher_discount_rate_means_lower_fair_value():
    cheap = dcf_fair_value(base_inputs(discount_rate=0.12))
    dear = dcf_fair_value(base_inputs(discount_rate=0.07))
    assert dear > cheap


def test_negative_fcf_returns_none():
    assert dcf_fair_value(base_inputs(base_fcf=-5)) is None


def test_discount_rate_below_terminal_growth_returns_none():
    assert dcf_fair_value(base_inputs(discount_rate=0.02, terminal_growth=0.025)) is None


def test_verdict_bands():
    assert verdict(35.0) == "undervalued"
    assert verdict(20.0) == "undervalued"
    assert verdict(0.0) == "fair"
    assert verdict(-19.9) == "fair"
    assert verdict(-25.0) == "overvalued"
    assert verdict(None) == "unknown"


def fundamentals(**overrides):
    data = {
        "symbol": "TEST",
        "name": "Test Corp",
        "currency": "USD",
        "beta": 1.2,
        "shares_outstanding": 50_000_000,
        "fcf_ttm": 100_000_000,
        "annual_fcf": {"2023-12-31": 80_000_000, "2024-12-31": 90_000_000},
        "shares_by_year": {"2023-12-31": 48_000_000, "2024-12-31": 49_000_000},
        "growth_estimate": {"rate": 0.12, "source": "test"},
        "analyst": {"target_mean": 55.0, "target_high": 70.0, "target_low": 40.0, "count": 5},
    }
    data.update(overrides)
    return data


PRICES = {"prices": [["2024-01-02", 30.0], ["2025-01-02", 40.0]], "current_price": 40.0}


def test_build_valuation_dcf_path():
    result = build_valuation(fundamentals(), PRICES, risk_free=0.045)
    assert result["method"] == "dcf"
    assert result["fair_value"] > 0
    assert result["upside_pct"] is not None
    # History: one point per annual FCF year plus the current TTM point.
    assert len(result["history"]["fair_values"]) == 3


def test_build_valuation_falls_back_to_analyst_target():
    result = build_valuation(fundamentals(fcf_ttm=-10, annual_fcf={}), PRICES, 0.045)
    assert result["method"] == "analyst_target"
    assert result["fair_value"] == 55.0
    assert result["upside_pct"] == 37.5


def test_low_fcf_yield_prefers_analyst_target():
    # 10M FCF on a 2B market cap = 0.5% yield: a trailing-FCF DCF is not
    # informative, so the analyst consensus becomes the primary fair value.
    result = build_valuation(fundamentals(fcf_ttm=10_000_000), PRICES, 0.045)
    assert result["method"] == "analyst_target"
    assert result["fair_value"] == 55.0
    # The DCF stays visible as a secondary figure...
    assert result["assumptions"]["dcf_fair_value"] is not None
    # ...but the chart only gets the single present-day analyst point.
    assert len(result["history"]["fair_values"]) == 1


def test_analyst_target_method_replays_consensus_history():
    history = [["2025-08-01", 20.0], ["2026-01-01", 40.0], ["2026-06-01", 88.0]]
    result = build_valuation(
        fundamentals(fcf_ttm=10_000_000), PRICES, 0.045, target_history=history
    )
    assert result["method"] == "analyst_target"
    # Three consensus revisions plus today's estimate.
    assert len(result["history"]["fair_values"]) == 4
    assert result["history"]["fair_values"][0] == ["2025-08-01", 20.0]
    assert result["history"]["analyst_targets"] == history


def test_build_valuation_handles_no_data():
    funds = fundamentals(
        fcf_ttm=None,
        annual_fcf={},
        analyst={"target_mean": None, "target_high": None, "target_low": None, "count": None},
    )
    result = build_valuation(funds, PRICES, 0.045)
    assert result["method"] == "unavailable"
    assert result["fair_value"] is None
    assert result["verdict"] == "unknown"


def test_growth_input_is_clamped():
    result = build_valuation(
        fundamentals(growth_estimate={"rate": 3.5, "source": "meme rally"}), PRICES, 0.045
    )
    assert result["assumptions"]["growth_rate"] <= 0.25
