"""ย้อนเทสต์กลยุทธ์บนข้อมูลย้อนหลัง แล้วสร้าง report.html ไว้เปิดเทียบกับกราฟ

python backtest.py            # ย้อนหลัง 365 วัน
python backtest.py 180        # ย้อนหลัง 180 วัน
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from strategy import Config, LEVEL_NAMES, fetch_klines, scan_both

HERE = os.path.dirname(os.path.abspath(__file__))
TH = timezone(timedelta(hours=7))
BAR_MS = 15 * 60 * 1000


def load_history(days):
    path = os.path.join(HERE, "data", f"btcusdt_15m_{days}d.csv")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 6 * 3600:
        with open(path, newline="") as f:
            return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5])) for r in csv.reader(f)]

    start = int(time.time() * 1000) - days * 86400 * 1000
    out = []
    while True:
        rows = fetch_klines(start_ms=start)
        if not rows:
            break
        out.extend(rows)
        start = rows[-1][0] + BAR_MS
        print(f"\rโหลดข้อมูล {len(out)} แท่ง", end="", flush=True)
        if len(rows) < 1000:
            break
    print()
    now = int(time.time() * 1000)
    out = [r for r in out if r[5] < now]  # เอาเฉพาะแท่งที่ปิดแล้ว
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(out)
    return out


def fmt_time(ms):
    return datetime.fromtimestamp(ms / 1000, TH).strftime("%Y-%m-%d %H:%M")


def evaluate(candles, ev, horizon=96):
    """ผลหลังเข้า: ใช้เส้นไกลสุด (long = เส้นล่าง, short = เส้นบน) เป็นจุดตัดขาดทุน
    แล้วดูว่าถึง 1R / 2R ก่อนโดนตัดไหม"""
    i, entry = ev["i"], ev["price"]
    sgn = 1 if ev["side"] == "long" else -1
    lv = [v for v in ev["levels"].values() if v is not None]
    stop = min(lv) if sgn == 1 else max(lv)
    risk = (entry - stop) * sgn
    res = {"risk_pct": risk / entry * 100, "r1": None, "r2": None, "stopped": False}
    best, worst = 0.0, 0.0  # กำไร/ขาดทุนสูงสุดระหว่างทาง (หน่วยราคา)
    for j in range(i + 1, min(i + 1 + horizon, len(candles))):
        _, _, h, l, c, _ = candles[j]
        fav, adv = (h, l) if sgn == 1 else (l, h)
        if (adv - stop) * sgn <= 0:
            res["stopped"] = True
            break
        best, worst = max(best, (fav - entry) * sgn), max(worst, (entry - adv) * sgn)
        if res["r1"] is None and best >= risk:
            res["r1"] = j - i
        if best >= 2 * risk:
            res["r2"] = j - i
            break
    res["mfe_pct"] = best / entry * 100
    res["mae_pct"] = worst / entry * 100
    return res


def chart_data(candles, e100, e200, ev_entry, ev_break):
    a = max(0, ev_break["base"][0] - 30)
    b = min(len(candles), ev_entry["i"] + 60)
    shift = 7 * 3600  # แสดงเป็นเวลาไทย
    t = lambda k: candles[k][0] // 1000 + shift
    return {
        "candles": [{"time": t(k), "open": candles[k][1], "high": candles[k][2],
                     "low": candles[k][3], "close": candles[k][4]} for k in range(a, b)],
        "ema100": [{"time": t(k), "value": e100[k]} for k in range(a, b) if e100[k]],
        "ema200": [{"time": t(k), "value": e200[k]} for k in range(a, b) if e200[k]],
        "levels": {k: v for k, v in ev_entry["levels"].items() if v is not None},
        "base": [t(ev_break["base"][0]), t(ev_break["base"][1])],
        "markers": [
            {"time": t(ev_break["i"]), "position": "belowBar", "color": "#f5c542", "shape": "arrowUp", "text": "ทะลุขึ้น"},
            {"time": t(ev_entry["i"]), "position": "belowBar", "color": "#2ecc71", "shape": "arrowUp", "text": "เข้า Long"},
        ] if ev_entry["side"] == "long" else [
            {"time": t(ev_break["i"]), "position": "aboveBar", "color": "#f5c542", "shape": "arrowDown", "text": "ทะลุลง"},
            {"time": t(ev_entry["i"]), "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "เข้า Short"},
        ],
        "level_names": LEVEL_NAMES[ev_entry["side"]],
    }


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    cfg = Config()
    candles = load_history(days)
    events, e100, e200 = scan_both(candles, cfg)
    by_i = {(e["side"], e["i"]): e for e in events if e["type"] == "breakout"}

    print(f"ช่วงข้อมูล: {fmt_time(candles[0][0])} ถึง {fmt_time(candles[-1][0])} ({len(candles)} แท่ง)")
    for side, label in (("long", "ทะลุขึ้น (Long)"), ("short", "ทะลุลง (Short)")):
        ev = [e for e in events if e["side"] == side]
        cancels = [e for e in ev if e["type"] == "cancel"]
        print(f"{label}: ทะลุ {sum(1 for e in ev if e['type'] == 'breakout')} | "
              f"เข้าได้ {sum(1 for e in ev if e['type'] == 'entry')} | ยกเลิก {len(cancels)}")
        for reason in sorted({e['reason'] for e in cancels}):
            print(f"  ยกเลิกเพราะ {reason}: {sum(1 for e in cancels if e['reason'] == reason)}")
    print()

    rows = []
    for e in (e for e in events if e["type"] == "entry"):
        r = evaluate(candles, e)
        result = "โดนตัด" if r["stopped"] and r["r1"] is None else ("ถึง 2R" if r["r2"] else ("ถึง 1R" if r["r1"] else "ยังไม่ถึง"))
        rows.append({"time": fmt_time(candles[e["i"]][0]), "price": e["price"], "side": e["side"],
                     "holding": LEVEL_NAMES[e["side"]][e["holding"]], "result": result, **r,
                     "chart": chart_data(candles, e100, e200, e, by_i[(e["side"], e["ref"])])})
        print(f"{rows[-1]['time']}  {e['side']:<5}  เข้า {e['price']:>10,.1f}  ยืน{rows[-1]['holding']:<8}  "
              f"เสี่ยง {r['risk_pct']:.2f}%  ไปทางกำไรสูงสุด {r['mfe_pct']:.2f}%  {result}")

    print()
    for side in ("long", "short"):
        rs = [r for r in rows if r["side"] == side]
        if rs:
            print(f"{side:<5}: ถึง 1R {sum(1 for r in rs if r['r1'])}/{len(rs)}   "
                  f"ถึง 2R {sum(1 for r in rs if r['r2'])}/{len(rs)}   "
                  f"โดนตัดก่อน 1R {sum(1 for r in rs if r['result'] == 'โดนตัด')}/{len(rs)}")

    with open(os.path.join(HERE, "report_template.html"), encoding="utf-8") as f:
        html = f.read()
    breaks = [e for e in events if e["type"] == "breakout"]
    summary = {"range": f"{fmt_time(candles[0][0])} – {fmt_time(candles[-1][0])}",
               "breakouts": len(breaks), "entries": len(rows),
               "cancels": sum(1 for e in events if e["type"] == "cancel")}
    html = html.replace("__DATA__", json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False))
    out = os.path.join(HERE, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nสร้างรายงาน: {out}")


if __name__ == "__main__":
    main()
