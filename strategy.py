"""กลยุทธ์ EMA100/EMA200 บน BTCUSDT 15 นาที

ขั้นตอน
1. ราคาอยู่ใต้ EMA200 (ช่วงเลี้ยงราคา) แล้วแท่งปิดทะลุเหนือ EMA200  -> แจ้ง "ทะลุ"
2. รอราคาย่อกลับลงมาแตะโซน EMA200
3. ด่านรับ (เช็คจากราคาปิด เรียงจากบนลงล่าง): EMA100, เส้นบน, เส้นกลาง, เส้นล่าง
4. ระหว่างย่อ ถ้ายังมีด่านที่ไม่หลุด แล้วเกิดแท่งเขียวปิดเหนือไฮแท่งก่อน -> แจ้ง "เข้าได้"
5. ปิดหลุดเส้นล่าง หรือรอนานเกินไป -> ยกเลิก

ฝั่งทะลุลง (short) ใช้กฎเดียวกันกลับด้านทั้งหมด ดู scan_both()

ใช้เฉพาะ standard library เพื่อให้รันบน GitHub Actions ได้โดยไม่ต้องติดตั้งอะไร
"""
import json
import urllib.request
from dataclasses import dataclass

BINANCE = "https://data-api.binance.vision/api/v3/klines"


@dataclass
class Config:
    ema_fast: int = 100
    ema_slow: int = 200
    lookback: int = 96       # ดูช่วงเลี้ยงราคาย้อนหลังสูงสุดกี่แท่ง (96 แท่ง = 24 ชม.)
    min_base: int = 16       # ต้องอยู่ใต้ EMA200 อย่างน้อยกี่แท่งก่อนทะลุ
    pivot: int = 3           # โลว์ต้องต่ำกว่าแท่งซ้าย/ขวากี่แท่งถึงนับเป็นจุดกลับตัว
    level_tol: float = 0.0015  # ระยะที่ถือว่าแตะเส้นเดียวกัน (0.15%)
    touch_tol: float = 0.001   # ย่อมาใกล้ EMA200 ไม่เกิน 0.1% ถือว่าย่อแล้ว
    max_wait: int = 96       # หลังทะลุ ถ้าไม่เกิดสัญญาณใน 96 แท่ง ให้ยกเลิก
    ride_window: int = 12    # ช่วงเลี้ยงราคา: ใน 12 แท่งก่อนทะลุ EMA200
    ride_min: int = 8        # ต้องปิดเหนือ EMA100 อย่างน้อย 8 แท่ง


def fetch_klines(symbol="BTCUSDT", interval="15m", limit=1000, start_ms=None, end_ms=None):
    url = f"{BINANCE}?symbol={symbol}&interval={interval}&limit={limit}"
    if start_ms is not None:
        url += f"&startTime={start_ms}"
    if end_ms is not None:
        url += f"&endTime={end_ms}"
    with urllib.request.urlopen(url, timeout=30) as r:
        rows = json.loads(r.read())
    # (open_time_ms, open, high, low, close, close_time_ms)
    return [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), int(k[6])) for k in rows]


def ema(values, n):
    """EMA แบบเดียวกับ TradingView (เริ่มต้นด้วยค่าเฉลี่ย n แท่งแรก)"""
    out = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    s = sum(values[:n]) / n
    out[n - 1] = s
    for i in range(n, len(values)):
        s = values[i] * k + s * (1 - k)
        out[i] = s
    return out


def find_levels(lows, start, end, cfg):
    """หาเส้นบน/กลาง/ล่าง จากช่วงเลี้ยงราคา lows[start..end]"""
    p = cfg.pivot
    bottom_i = min(range(start, end + 1), key=lambda j: lows[j])
    bottom = lows[bottom_i]

    pivots = [j for j in range(start + p, end - p + 1)
              if lows[j] < min(lows[j - p:j]) and lows[j] <= min(lows[j + 1:j + p + 1])]

    # ใช้ abs() เพื่อให้ใช้ได้กับราคาที่กลับเครื่องหมาย (ฝั่ง short)
    top = None
    if pivots and pivots[-1] != bottom_i and lows[pivots[-1]] > bottom + abs(bottom) * cfg.level_tol:
        top = lows[pivots[-1]]

    mid = None
    if top is not None:
        best = None
        for j in pivots:
            lv = lows[j]
            if bottom + abs(bottom) * cfg.level_tol < lv < top - abs(top) * cfg.level_tol:
                touches = sum(1 for x in lows[start:end + 1] if abs(x - lv) / abs(lv) <= cfg.level_tol)
                if best is None or touches >= best[0]:
                    best = (touches, lv)
        if best is not None:
            mid = best[1]

    return {"top": top, "mid": mid, "bottom": bottom}


LEVEL_NAMES = {
    "long": {"ema100": "EMA100", "top": "เส้นบน", "mid": "เส้นกลาง", "bottom": "เส้นล่าง"},
    # ฝั่ง short: เส้นที่ใกล้ราคาที่สุดคือเส้นต้านล่าง
    "short": {"ema100": "EMA100", "top": "เส้นล่าง", "mid": "เส้นกลาง", "bottom": "เส้นบน"},
}


def flip(candles):
    """กลับเครื่องหมายราคา เพื่อใช้กฎฝั่งขึ้นตรวจฝั่งลงได้แบบสมมาตรพอดี (EMA กลับเครื่องหมายตามด้วย)"""
    return [(t, -o, -l, -h, -c, ct) for t, o, h, l, c, ct in candles]


def scan_both(candles, cfg=Config()):
    """สัญญาณทั้งฝั่งทะลุขึ้น (long) และทะลุลง (short) โดยราคาในผลลัพธ์เป็นราคาจริงทั้งหมด"""
    long_ev, e100, e200 = scan(candles, cfg)
    short_ev, _, _ = scan(flip(candles), cfg)
    for e in long_ev:
        e["side"] = "long"
    for e in short_ev:
        e["side"] = "short"
        for k in ("price", "ema100", "ema200", "holding_price"):
            if k in e:
                e[k] = -e[k]
        if "levels" in e:
            e["levels"] = {k: (-v if v is not None else None) for k, v in e["levels"].items()}
    return sorted(long_ev + short_ev, key=lambda e: e["i"]), e100, e200


def scan(candles, cfg=Config()):
    """ไล่ทุกแท่ง (ที่ปิดแล้ว) แล้วคืนรายการเหตุการณ์ breakout / entry / cancel"""
    o = [c[1] for c in candles]
    h = [c[2] for c in candles]
    l = [c[3] for c in candles]
    c = [c[4] for c in candles]
    e100 = ema(c, cfg.ema_fast)
    e200 = ema(c, cfg.ema_slow)

    events = []
    below_start = None
    st = None

    for i in range(cfg.ema_slow, len(candles)):
        if st is None:
            riding = sum(1 for j in range(i - cfg.ride_window, i) if c[j] > e100[j])
            if (below_start is not None and c[i] > e200[i] and c[i - 1] <= e200[i - 1]
                    and e100[i] < e200[i]             # มาจากขาลง: EMA100 ยังอยู่ใต้ EMA200
                    and riding >= cfg.ride_min):      # เลี้ยงราคาเหนือ EMA100 มาก่อน
                bs, be = max(below_start, i - cfg.lookback), i - 1
                if be - bs + 1 >= cfg.min_base:
                    lv = find_levels(l, bs, be, cfg)
                    st = {"breakout": i, "base": (bs, be), "levels": lv, "pulled": False, "broken": set()}
                    events.append({"type": "breakout", "i": i, "price": c[i],
                                   "ema100": e100[i], "ema200": e200[i], "levels": lv, "base": (bs, be)})
        else:
            if i - st["breakout"] > cfg.max_wait:
                events.append({"type": "cancel", "i": i, "reason": "ไม่ย่อ/ไม่เด้งภายในเวลา", "ref": st["breakout"]})
                st = None
            else:
                if l[i] <= e200[i] + abs(e200[i]) * cfg.touch_tol:
                    st["pulled"] = True
                defenses = {"ema100": e100[i], **{k: v for k, v in st["levels"].items() if v is not None}}
                for k, v in defenses.items():
                    if c[i] < v:
                        st["broken"].add(k)
                holding = sorted((v, k) for k, v in defenses.items() if k not in st["broken"])
                if not holding:
                    events.append({"type": "cancel", "i": i, "reason": "ปิดหลุดด่านสุดท้าย", "ref": st["breakout"]})
                    st = None
                elif st["pulled"] and c[i] > o[i] and c[i] > h[i - 1]:
                    # ด่านที่ยืนอยู่ = ด่านที่ไม่หลุดและอยู่ใต้ราคามากที่สุด (ใกล้ราคาที่สุด)
                    under = [(v, k) for v, k in holding if v <= c[i]]
                    v, k = under[-1] if under else holding[0]
                    events.append({"type": "entry", "i": i, "price": c[i], "ema100": e100[i], "ema200": e200[i],
                                   "holding": k, "holding_price": v, "levels": st["levels"],
                                   "broken": sorted(st["broken"]), "ref": st["breakout"]})
                    st = None

        if c[i] <= e200[i]:
            if below_start is None:
                below_start = i
        else:
            below_start = None

    return events, e100, e200
