"""
短线信号：校验 → 存储 → 用后续小时线自动结算 → 统计战绩。

这里全是纯函数（不碰网络/Redis），方便单元测试。
结算规则刻意保守：
  - 入场：价格触及 entry 才算成交；跳空越过 entry 时按开盘价成交
  - 成交当根 K 线只检查止损，不检查止盈（无法确定 K 线内先后顺序）
  - 同一根 K 线同时触及止损和止盈 → 记为止损
  - 到期未成交 → NOT_TRIGGERED（不计入胜率）
  - 成交后到期仍未触及止损/止盈 → EXPIRED，按最后收盘价计算 R
"""
from datetime import datetime, timedelta, timezone

MAX_SIGNALS_PER_RUN = 3
MIN_RR              = 1.5    # 最低盈亏比
MIN_STOP_ATR        = 0.3    # 止损距离下限（单位：日 ATR）
MAX_STOP_ATR        = 3.0    # 止损距离上限
MAX_ENTRY_ATR       = 1.5    # 入场价距现价上限，超过说明 1-5 天内不现实
MAX_HORIZON_DAYS    = 5

OPEN_STATUSES   = ("PENDING", "OPEN")
CLOSED_STATUSES = ("WIN", "LOSS", "EXPIRED")


def is_24x7(symbol: str) -> bool:
    """加密货币全天候交易，其余按工作日计算持仓周期。"""
    return symbol.upper().endswith("-USD")


def add_trading_days(start: datetime, days: int, symbol: str) -> datetime:
    if is_24x7(symbol):
        return start + timedelta(days=days)
    d = start
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def validate_signal(sig: dict, market: dict) -> tuple[dict | None, str]:
    """
    校验 LLM 给出的信号。返回 (规范化后的信号, "") 或 (None, 剔除原因)。
    market: QuantDataEngine 的输出，至少需要 price 和 ATR_14。
    """
    sym = str(sig.get("symbol", "")).upper().strip()
    if sym not in market:
        return None, f"{sym or '?'}: 不在本期数据中"

    direction = str(sig.get("direction", "")).upper()
    if direction not in ("LONG", "SHORT"):
        return None, f"{sym}: 方向无效 ({direction})"

    try:
        entry  = float(sig["entry"])
        stop   = float(sig["stop"])
        target = float(sig["target"])
    except (KeyError, TypeError, ValueError):
        return None, f"{sym}: 入场/止损/目标价缺失"

    price = market[sym]["price"]
    atr   = market[sym].get("ATR_14") or 0.0
    if atr <= 0:
        return None, f"{sym}: ATR 不可用，无法评估风险"

    if direction == "LONG" and not (stop < entry < target):
        return None, f"{sym}: 做多需满足 止损 < 入场 < 目标"
    if direction == "SHORT" and not (target < entry < stop):
        return None, f"{sym}: 做空需满足 目标 < 入场 < 止损"

    risk   = abs(entry - stop)
    reward = abs(target - entry)
    rr     = reward / risk

    if rr < MIN_RR:
        return None, f"{sym}: 盈亏比 {rr:.2f} < {MIN_RR}"
    stop_atr = risk / atr
    if not (MIN_STOP_ATR <= stop_atr <= MAX_STOP_ATR):
        return None, f"{sym}: 止损距离 {stop_atr:.2f} ATR 超出 [{MIN_STOP_ATR}, {MAX_STOP_ATR}]"
    entry_atr = abs(entry - price) / atr
    if entry_atr > MAX_ENTRY_ATR:
        return None, f"{sym}: 入场价距现价 {entry_atr:.2f} ATR，短线内不现实"

    try:
        horizon = int(sig.get("horizon_days", 3))
    except (TypeError, ValueError):
        horizon = 3
    horizon = max(1, min(MAX_HORIZON_DAYS, horizon))

    confidence = str(sig.get("confidence", "LOW")).upper()
    if confidence not in ("HIGH", "MEDIUM", "LOW"):
        confidence = "LOW"

    return {
        "symbol":       sym,
        "direction":    direction,
        "entry":        entry,
        "stop":         stop,
        "target":       target,
        "rr":           round(rr, 2),
        "stop_atr":     round(stop_atr, 2),
        "horizon_days": horizon,
        "confidence":   confidence,
        "rationale":    str(sig.get("rationale", ""))[:300],
        "invalidation": str(sig.get("invalidation", ""))[:200],
        "ref_price":    price,
    }, ""


def new_signal_record(sig: dict, created: datetime) -> dict:
    """在校验通过的信号上加上生命周期字段。created 必须带时区。"""
    created_utc = created.astimezone(timezone.utc)
    expires     = add_trading_days(created_utc, sig["horizon_days"], sig["symbol"])
    return {
        **sig,
        "id":         f"{sig['symbol']}-{int(created_utc.timestamp())}",
        "created_ts": int(created_utc.timestamp()),
        "expires_ts": int(expires.timestamp()),
        "status":     "PENDING",
        "fill_ts":    None,
        "fill_price": None,
        "exit_ts":    None,
        "exit_price": None,
        "r_multiple": None,
    }


def _r(sig: dict, exit_price: float) -> float:
    risk = abs(sig["fill_price"] - sig["stop"])
    if risk == 0:
        return 0.0
    move = exit_price - sig["fill_price"]
    if sig["direction"] == "SHORT":
        move = -move
    return round(move / risk, 2)


def evaluate_signal(sig: dict, bars: list[dict], now_ts: int) -> dict:
    """
    用 created_ts 之后的小时线推进一个未结算信号的状态。
    bars: [{"time": unix 秒(K 线开始), "open", "high", "low", "close"}]，按时间升序。
    返回新的 dict，不修改入参。
    """
    sig = dict(sig)
    if sig["status"] not in OPEN_STATUSES:
        return sig

    is_long = sig["direction"] == "LONG"
    entry, stop, target = sig["entry"], sig["stop"], sig["target"]
    breakout = (entry > sig["ref_price"]) if is_long else (entry < sig["ref_price"])

    last_close = None
    for bar in bars:
        t = bar["time"]
        if t < sig["created_ts"]:
            continue
        if t >= sig["expires_ts"]:
            break
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        last_close = c

        if sig["status"] == "PENDING":
            if is_long:
                hit = (h >= entry) if breakout else (l <= entry)
                gap = (o > entry) if breakout else (o < entry)
            else:
                hit = (l <= entry) if breakout else (h >= entry)
                gap = (o < entry) if breakout else (o > entry)
            if not hit:
                continue
            sig["status"]     = "OPEN"
            sig["fill_ts"]    = t
            sig["fill_price"] = o if gap else entry
            # 成交当根只检查止损（保守）
            stopped = (l <= stop) if is_long else (h >= stop)
            if stopped:
                sig.update(status="LOSS", exit_ts=t, exit_price=stop)
                sig["r_multiple"] = _r(sig, stop)
                return sig
            continue

        # OPEN：同根同时触及 → 记止损
        stopped = (l <= stop)   if is_long else (h >= stop)
        tp_hit  = (h >= target) if is_long else (l <= target)
        if stopped:
            exit_px = min(o, stop) if is_long else max(o, stop)  # 跳空穿越止损按开盘价
            sig.update(status="LOSS", exit_ts=t, exit_price=exit_px)
            sig["r_multiple"] = _r(sig, exit_px)
            return sig
        if tp_hit:
            exit_px = max(o, target) if is_long else min(o, target)
            sig.update(status="WIN", exit_ts=t, exit_price=exit_px)
            sig["r_multiple"] = _r(sig, exit_px)
            return sig

    if now_ts >= sig["expires_ts"]:
        if sig["status"] == "PENDING":
            sig["status"] = "NOT_TRIGGERED"
        elif last_close is not None:
            sig.update(status="EXPIRED", exit_ts=sig["expires_ts"], exit_price=last_close)
            sig["r_multiple"] = _r(sig, last_close)
        else:
            sig.update(status="EXPIRED", exit_ts=sig["expires_ts"],
                       exit_price=sig["fill_price"], r_multiple=0.0)
    return sig


def compute_stats(signals: list[dict]) -> dict:
    closed = [s for s in signals if s["status"] in CLOSED_STATUSES]
    wins   = [s for s in closed if (s.get("r_multiple") or 0) > 0]
    rs     = [s.get("r_multiple") or 0.0 for s in closed]

    by_conf = {}
    for conf in ("HIGH", "MEDIUM", "LOW"):
        grp = [s for s in closed if s["confidence"] == conf]
        if grp:
            by_conf[conf] = {
                "n":        len(grp),
                "win_rate": round(sum(1 for s in grp if (s.get("r_multiple") or 0) > 0) / len(grp) * 100, 1),
                "avg_r":    round(sum(s.get("r_multiple") or 0 for s in grp) / len(grp), 2),
            }

    return {
        "closed":        len(closed),
        "open":          sum(1 for s in signals if s["status"] in OPEN_STATUSES),
        "not_triggered": sum(1 for s in signals if s["status"] == "NOT_TRIGGERED"),
        "win_rate":      round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avg_r":         round(sum(rs) / len(rs), 2) if rs else None,
        "total_r":       round(sum(rs), 2),
        "by_confidence": by_conf,
    }
