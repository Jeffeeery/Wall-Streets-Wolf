from datetime import datetime, timezone

from signals import (
    add_trading_days,
    compute_stats,
    evaluate_signal,
    new_signal_record,
    validate_signal,
)

MARKET = {"NVDA": {"price": 100.0, "ATR_14": 4.0}}
CREATED = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)  # 周一
H = 3600


def make(direction="LONG", entry=100.0, stop=96.0, target=108.0, **kw):
    raw = dict(symbol="NVDA", direction=direction, entry=entry, stop=stop,
               target=target, horizon_days=3, confidence="MEDIUM", rationale="x", **kw)
    sig, reason = validate_signal(raw, MARKET)
    assert sig, reason
    return new_signal_record(sig, CREATED)


def bar(i, o, h, l, c):
    return {"time": int(CREATED.timestamp()) + i * H, "open": o, "high": h, "low": l, "close": c}


# ---------- validate ----------
def test_rejects_bad_ordering():
    sig, reason = validate_signal(
        dict(symbol="NVDA", direction="LONG", entry=100, stop=104, target=110), MARKET)
    assert sig is None and "止损" in reason


def test_rejects_low_rr():
    sig, reason = validate_signal(
        dict(symbol="NVDA", direction="LONG", entry=100, stop=96, target=104), MARKET)
    assert sig is None and "盈亏比" in reason


def test_rejects_stop_too_wide_and_entry_too_far():
    assert validate_signal(dict(symbol="NVDA", direction="LONG", entry=100, stop=80, target=140), MARKET)[0] is None
    assert validate_signal(dict(symbol="NVDA", direction="LONG", entry=110, stop=106, target=118), MARKET)[0] is None


def test_rejects_unknown_symbol_and_clamps_horizon():
    assert validate_signal(dict(symbol="TSLA", direction="LONG", entry=1, stop=0.5, target=2), MARKET)[0] is None
    sig, _ = validate_signal(dict(symbol="nvda", direction="short", entry=100, stop=104, target=92,
                                  horizon_days=30), MARKET)
    assert sig["symbol"] == "NVDA" and sig["horizon_days"] == 5 and sig["rr"] == 2.0


# ---------- lifecycle ----------
def test_business_day_expiry_skips_weekend():
    fri = datetime(2026, 10, 30, tzinfo=timezone.utc)
    assert add_trading_days(fri, 1, "NVDA").weekday() == 0
    assert add_trading_days(fri, 1, "BTC-USD").weekday() == 5


def test_win_after_fill():
    s = make()
    out = evaluate_signal(s, [bar(0, 101, 101, 99.5, 100.5), bar(1, 100.5, 108.5, 100, 108)], s["created_ts"] + 2 * H)
    assert out["status"] == "WIN" and out["r_multiple"] == 2.0


def test_same_bar_stop_and_target_counts_as_loss():
    s = make()
    out = evaluate_signal(s, [bar(0, 101, 101, 99.5, 100.5), bar(1, 100, 109, 95, 100)], s["created_ts"] + 2 * H)
    assert out["status"] == "LOSS" and out["r_multiple"] == -1.0


def test_fill_bar_only_checks_stop():
    s = make()
    # 成交当根触及目标价但不算止盈
    out = evaluate_signal(s, [bar(0, 101, 109, 99.5, 108)], s["created_ts"] + H)
    assert out["status"] == "OPEN"


def test_gap_through_stop_fills_at_open():
    s = make()
    out = evaluate_signal(s, [bar(0, 101, 101, 99.5, 100), bar(1, 94, 95, 93, 94)], s["created_ts"] + 2 * H)
    assert out["status"] == "LOSS" and out["exit_price"] == 94 and out["r_multiple"] == -1.5


def test_breakout_long_and_short():
    s = make(entry=102, stop=98, target=110)  # 高于现价 → 突破单
    out = evaluate_signal(s, [bar(0, 100, 101, 99, 100), bar(1, 100, 102.5, 100, 102)], s["created_ts"] + 2 * H)
    assert out["status"] == "OPEN" and out["fill_price"] == 102

    s = make(direction="SHORT", entry=101, stop=105, target=93)  # 高于现价的做空 → 反弹挂单
    out = evaluate_signal(s, [bar(0, 100, 101.2, 99, 100), bar(1, 100, 100, 92.5, 93)], s["created_ts"] + 2 * H)
    assert out["status"] == "WIN" and out["r_multiple"] == 2.0


def test_not_triggered_and_expired():
    s = make(entry=98, stop=94, target=106)
    out = evaluate_signal(s, [bar(0, 100, 101, 99, 100)], s["expires_ts"] + 1)
    assert out["status"] == "NOT_TRIGGERED"

    s = make()
    out = evaluate_signal(s, [bar(0, 101, 101, 99.5, 100), bar(1, 100, 103, 99, 102)], s["expires_ts"] + 1)
    assert out["status"] == "EXPIRED" and out["r_multiple"] == 0.5


def test_still_pending_before_expiry_and_bars_after_expiry_ignored():
    s = make(entry=98, stop=94, target=106)
    assert evaluate_signal(s, [bar(0, 100, 101, 99, 100)], s["created_ts"] + H)["status"] == "PENDING"
    late = {"time": s["expires_ts"] + H, "open": 97, "high": 97, "low": 90, "close": 91}
    assert evaluate_signal(s, [late], s["expires_ts"] + 2 * H)["status"] == "NOT_TRIGGERED"


def test_stats():
    sigs = [
        {"status": "WIN", "r_multiple": 2.0, "confidence": "HIGH"},
        {"status": "LOSS", "r_multiple": -1.0, "confidence": "HIGH"},
        {"status": "EXPIRED", "r_multiple": 0.3, "confidence": "LOW"},
        {"status": "NOT_TRIGGERED", "r_multiple": None, "confidence": "LOW"},
        {"status": "OPEN", "r_multiple": None, "confidence": "LOW"},
    ]
    st = compute_stats(sigs)
    assert st["closed"] == 3 and st["open"] == 1 and st["not_triggered"] == 1
    assert st["win_rate"] == 66.7 and st["total_r"] == 1.3
    assert st["by_confidence"]["HIGH"] == {"n": 2, "win_rate": 50.0, "avg_r": 0.5}
