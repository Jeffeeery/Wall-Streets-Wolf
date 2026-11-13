"""方向命中率：只用历史记录 + 日线核对，不联网，不碰 Tavily / 模型。"""
from datetime import datetime, timezone

import main
from test_pipeline import Resp, yahoo_payload


def ts(day, hour=14, minute=30):
    """2026 年 11 月某天的 UTC 时间戳；美股日线的时间戳是开盘时间 14:30 UTC。"""
    return int(datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).timestamp())


def row(time, calls, snapshot):
    """一条 analysis_history 记录：outlook 只有方向，置信度在 brief.outlook 里。"""
    return {
        "analysis_time": time,
        "snapshot": snapshot,
        "outlook": {s: d for s, d, _ in calls},
        "brief_outlook": [{"symbol": s, "direction": d, "confidence": c} for s, d, c in calls],
    }


def week(*closes):
    """11 月 2 日（周一）起连续几个交易日的收盘价。"""
    return [(ts(2 + i), c) for i, c in enumerate(closes)]


NOW = ts(10)
PRE_OPEN = "2026-11-02 20:00"   # 吉隆坡 20:00 = 12:00 UTC，美股还没开盘


def test_hit_miss_and_neutral_skipped():
    rows = [row(PRE_OPEN,
                [("NVDA", "BULLISH", "HIGH"), ("AAPL", "BEARISH", "MEDIUM"), ("GC=F", "NEUTRAL", "LOW")],
                {"NVDA": 100, "AAPL": 200, "GC=F": 4000})]
    bars = {"NVDA": week(99, 101, 103, 90), "AAPL": week(190, 195, 205, 150), "GC=F": week(1, 2, 3, 4)}
    r = main.score_direction_calls(rows, bars, 3, NOW)

    # 第 3 个交易日（11-04）收盘：NVDA 103 > 100 命中；AAPL 205 > 200，利空没中
    assert r["overall"] == {"hits": 1, "total": 2, "hit_rate": None, "insufficient": True}
    assert (r["by_confidence"]["HIGH"]["hits"], r["by_confidence"]["HIGH"]["total"]) == (1, 1)
    assert (r["by_confidence"]["MEDIUM"]["hits"], r["by_confidence"]["MEDIUM"]["total"]) == (0, 1)
    assert r["by_confidence"]["LOW"]["total"] == 0
    assert set(r["by_symbol"]) == {"NVDA", "AAPL"}   # 中性不计分
    assert r["open"] == 0 and r["skipped"] == 0 and r["days"] == 3

    # 换成 1 个交易日：NVDA 99 < 100 没中，AAPL 190 < 200 命中
    one = main.score_direction_calls(rows, bars, 1, NOW)
    assert one["by_symbol"]["NVDA"]["hits"] == 0 and one["by_symbol"]["AAPL"]["hits"] == 1


def test_flat_close_is_a_miss():
    rows = [row(PRE_OPEN, [("NVDA", "BULLISH", "LOW")], {"NVDA": 100})]
    r = main.score_direction_calls(rows, {"NVDA": week(1, 1, 100)}, 3, NOW)
    assert r["overall"]["hits"] == 0 and r["overall"]["total"] == 1


def test_run_after_the_close_counts_from_next_session():
    # 吉隆坡 11-03 07:00 = 11-02 23:00 UTC，当天日线已经收盘，从 11-03 起算，第 3 天是 11-05
    rows = [row("2026-11-03 07:00", [("NVDA", "BULLISH", "HIGH")], {"NVDA": 100})]
    r = main.score_direction_calls(rows, {"NVDA": week(1, 1, 150, 90)}, 3, NOW)
    assert r["overall"]["hits"] == 0 and r["overall"]["total"] == 1


def test_open_until_the_last_bar_is_complete():
    rows = [row(PRE_OPEN, [("NVDA", "BULLISH", "HIGH")], {"NVDA": 100})]
    bars = {"NVDA": week(101, 102, 103)}

    # 11-04 盘中：第 3 根日线的 close 还是现价，不计分；开盘满 24 小时后才算
    live = main.score_direction_calls(rows, bars, 3, ts(4, 18))
    assert live["open"] == 1 and live["overall"]["total"] == 0 and live["by_symbol"] == {}

    done = main.score_direction_calls(rows, bars, 3, ts(5, 14, 30))
    assert done["open"] == 0 and done["overall"]["hits"] == 1

    # 只有两根日线：同样是未到期
    short = main.score_direction_calls(rows, {"NVDA": week(101, 102)}, 3, NOW)
    assert short["open"] == 1 and short["overall"]["total"] == 0


def test_legacy_and_broken_rows():
    bars = {"NVDA": week(101, 102, 103)}
    rows = [
        # v3 之前的记录：没有 outlook，整条忽略
        {"analysis_time": PRE_OPEN, "conclusion": "---", "snapshot": {"NVDA": 100}},
        {"analysis_time": PRE_OPEN, "snapshot": {"NVDA": 100}, "outlook": None, "brief_outlook": None},
        # 只有方向、没有 brief：计入总体和品种，不进置信度分组
        {"analysis_time": PRE_OPEN, "snapshot": {"NVDA": 100}, "outlook": {"NVDA": "BULLISH"}},
        # 时间格式不对：忽略
        row("11/02 20:00", [("NVDA", "BULLISH", "HIGH")], {"NVDA": 100}),
        # 当期没拿到价格 / 拉不到日线：skipped
        row(PRE_OPEN, [("NVDA", "BULLISH", "HIGH")], None),
        row(PRE_OPEN, [("TSLA", "BEARISH", "LOW")], {"TSLA": 300}),
    ]
    r = main.score_direction_calls(rows, bars, 3, NOW)
    assert r["overall"]["hits"] == 1 and r["overall"]["total"] == 1
    assert all(b["total"] == 0 for b in r["by_confidence"].values())
    assert r["by_symbol"]["NVDA"]["total"] == 1
    assert r["skipped"] == 2 and r["open"] == 0


def test_percentage_only_with_enough_samples():
    hit  = row(PRE_OPEN, [("NVDA", "BULLISH", "HIGH")], {"NVDA": 100})
    miss = row(PRE_OPEN, [("NVDA", "BULLISH", "HIGH")], {"NVDA": 110})
    bars = {"NVDA": week(101, 102, 103)}

    nine = main.score_direction_calls([hit] * 6 + [miss] * 3, bars, 3, NOW)
    assert nine["overall"] == {"hits": 6, "total": 9, "hit_rate": None, "insufficient": True}

    ten = main.score_direction_calls([hit] * 7 + [miss] * 3, bars, 3, NOW)
    assert ten["min_sample"] == 10
    assert ten["overall"] == {"hits": 7, "total": 10, "hit_rate": 70.0, "insufficient": False}
    assert ten["by_confidence"]["HIGH"]["hit_rate"] == 70.0
    assert ten["by_confidence"]["MEDIUM"] == {"hits": 0, "total": 0, "hit_rate": None, "insufficient": True}
    assert ten["by_symbol"]["NVDA"]["hit_rate"] == 70.0


def test_hit_rate_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "SUPABASE_URL", "http://sb")
    monkeypatch.setattr(main, "SUPABASE_KEY", "k")
    # yahoo_payload 的日线从 2023-11-14 22:13 UTC 起每天一根；这次运行在 11-15 00:00 UTC
    rows = [
        row("2023-11-15 08:00",
            [("NVDA", "BULLISH", "HIGH"), ("AAPL", "BEARISH", "LOW"), ("GC=F", "NEUTRAL", "LOW")],
            {"NVDA": 100, "AAPL": 100, "GC=F": 100}),
        {"analysis_time": "2023-11-01 08:00", "snapshot": {"NVDA": 90}},
    ]
    sb, yahoo = [], []

    def fake_get(url, **kw):
        if "analysis_history" in url:
            sb.append(kw["params"])
            return Resp(rows)
        yahoo.append(url)
        if "AAPL" in url:
            raise RuntimeError("yahoo down")
        return Resp(yahoo_payload(n=30))

    def no_post(*a, **kw):
        raise AssertionError("命中率不应该调用 Tavily / 模型 / Telegram")

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", no_post)
    client = TestClient(main.app)

    r = client.get("/api/stats/hit-rate").json()
    assert r["days"] == 3
    assert r["overall"]["hits"] == 1 and r["overall"]["total"] == 1   # 第 3 根收盘 102.23 > 100
    assert r["by_symbol"]["NVDA"]["total"] == 1 and r["skipped"] == 1  # AAPL 拉不到日线
    # 只取打分要用的列，每个要打分的品种只拉一次日线，中性的不拉
    assert "brief_outlook:brief->outlook" in sb[0]["select"] and "report" not in sb[0]["select"]
    assert len(yahoo) == 2 and not any("GC=F" in u for u in yahoo)
    assert all("interval=1d" in u for u in yahoo)

    assert client.get("/api/stats/hit-rate?days=5").json()["days"] == 5
    assert client.get("/api/stats/hit-rate?days=0").status_code == 422
    assert client.get("/api/stats/hit-rate?days=6").status_code == 422
