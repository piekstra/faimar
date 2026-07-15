from app.history import FairValueLog
from app.valuation import merge_fair_value_history


def test_series_keeps_only_meaningful_revisions(tmp_path):
    log = FairValueLog(tmp_path / "h.db")
    log.record("T", "2026-07-01", 100.0, "dcf")
    log.record("T", "2026-07-02", 100.5, "dcf")  # 0.5% wobble — collapsed
    log.record("T", "2026-07-03", 105.0, "dcf")  # real revision — kept
    assert log.series("T") == [["2026-07-01", 100.0], ["2026-07-03", 105.0]]


def test_same_day_record_overwrites(tmp_path):
    log = FairValueLog(tmp_path / "h.db")
    log.record("T", "2026-07-01", 100.0, "dcf")
    log.record("T", "2026-07-01", 120.0, "analyst_target")
    assert log.series("T") == [["2026-07-01", 120.0]]


def test_series_is_per_symbol(tmp_path):
    log = FairValueLog(tmp_path / "h.db")
    log.record("A", "2026-07-01", 10.0, "dcf")
    log.record("B", "2026-07-01", 99.0, "dcf")
    assert log.series("A") == [["2026-07-01", 10.0]]


def test_merge_prefers_logged_value_on_collision():
    model = [["2025-09-30", 120.0], ["2026-07-15", 169.0]]
    logged = [["2026-07-01", 150.0], ["2026-07-15", 171.0]]
    merged = merge_fair_value_history(model, logged)
    assert merged == [
        ["2025-09-30", 120.0],
        ["2026-07-01", 150.0],
        ["2026-07-15", 171.0],
    ]
