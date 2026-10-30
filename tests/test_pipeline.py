"""端到端：mock 掉 Yahoo / Gemini / Redis / Telegram / Supabase，跑一遍完整流程。"""
import json
import math

import main


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v):
        self.store[k] = v


class Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data


def yahoo_payload(n, step, base):
    ts = [1_700_000_000 + i * step for i in range(n)]
    closes = [base + 5 * math.sin(i / 7) + i * 0.05 for i in range(n)]
    return {"chart": {"result": [{
        "meta": {"currentTradingPeriod": {"regular": {"start": 0, "end": 1}}},
        "timestamp": ts,
        "indicators": {"quote": [{
            "open": closes, "close": closes,
            "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
            "volume": [1000] * n,
        }]},
    }]}}


def test_full_run(monkeypatch):
    redis = FakeRedis()
    redis.store["marcus_watchlist"] = json.dumps(["NVDA", "AAPL"])
    monkeypatch.setattr(main, "get_redis", lambda: redis)
    sent, inserted = [], []

    def fake_get(url, **kw):
        assert "AAPL" in url or "NVDA" in url
        return Resp(yahoo_payload(400, 3600, 100) if "interval=1h" in url else yahoo_payload(250, 86400, 100))

    def fake_post(url, json=None, **kw):
        if "generativelanguage" in url:
            price = main.QuantDataEngine.fetch_and_calculate(["NVDA"])["NVDA"]["price"]
            body = {
                "conclusion": "NVDA 回踩 S1 做多", "regime": "MIXED",
                "assets": [{"symbol": "NVDA", "bias": "LONG", "note": "RSI_14=55", "levels": "S1"}],
                "signals": [
                    {"symbol": "NVDA", "direction": "LONG", "entry": price, "stop": price - 1.5,
                     "target": price + 4, "horizon_days": 3, "confidence": "HIGH", "rationale": "<test>"},
                    {"symbol": "AAPL", "direction": "LONG", "entry": 1, "stop": 2, "target": 3,
                     "horizon_days": 3, "confidence": "LOW", "rationale": "bad"},
                ],
                "review": "首次运行", "risk": "数据有限",
            }
            return Resp({"candidates": [{"content": {"parts": [{"text": __import__("json").dumps(body)}]}}]})
        if "telegram" in url:
            sent.append(json)
            return Resp({"ok": True})
        inserted.append(json)
        return Resp({}, 201)

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "SUPABASE_URL", "http://sb")
    monkeypatch.setattr(main, "SUPABASE_KEY", "k")

    msg = main.MarcusAgent.execute_and_send()
    assert "新信号 1" in msg and "剔除 1" in msg

    signals = json.loads(redis.store["marcus_signals"])
    assert len(signals) == 1 and signals[0]["symbol"] == "NVDA" and signals[0]["status"] == "PENDING"

    brief = sent[0]["text"]
    assert sent[0]["parse_mode"] == "HTML" and "&lt;test&gt;" in brief and "风控剔除 1" in brief

    mem = json.loads(redis.store["marcus_memory"])
    assert "【风控剔除】" in mem["report"] and mem["stats"]["open"] == 1
    assert inserted[0]["signals"][0]["symbol"] == "NVDA"

    # 第二次运行：已有进行中信号的品种不再重复开仓，且信号被结算推进
    main.MarcusAgent.execute_and_send()
    signals = json.loads(redis.store["marcus_signals"])
    assert len(signals) == 1

    # API
    from fastapi.testclient import TestClient
    r = TestClient(main.app).get("/api/signals").json()
    assert r["stats"]["open"] + r["stats"]["closed"] + r["stats"]["not_triggered"] == 1
