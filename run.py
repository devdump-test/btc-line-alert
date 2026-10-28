"""ตัวรันจริง: เช็คแท่ง 15 นาทีที่ปิดล่าสุด แล้วส่ง LINE เมื่อเกิดสัญญาณ

python run.py            # เช็คแล้วส่ง LINE
python run.py --dry      # เช็คอย่างเดียว พิมพ์ข้อความออกจอ ไม่ส่ง

เก็บเวลาแท่งล่าสุดที่เช็คแล้วไว้ใน state.json เพื่อไม่ให้แจ้งซ้ำ และไม่พลาดแท่ง
ถ้ารอบไหนรันช้า (GitHub Actions บางครั้งช้าไปหลายนาที)
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from strategy import Config, LEVEL_NAMES, fetch_klines, scan_both

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
TH = timezone(timedelta(hours=7))
FIRST_RUN_LOOKBACK_MS = 2 * 3600 * 1000  # รันครั้งแรก แจ้งเฉพาะสัญญาณใน 2 ชม. ล่าสุด


def fmt_price(v):
    return f"{v:,.0f}"


def message(e, candle):
    t = datetime.fromtimestamp(candle[0] / 1000, TH).strftime("%d/%m %H:%M")  # เวลาแท่งแบบ TradingView
    long = e["side"] == "long"
    names = LEVEL_NAMES[e["side"]]
    lv = e.get("levels", {})
    lines_txt = "\n".join(f"  {names[k]}: {fmt_price(lv[k])}" for k in ("top", "mid", "bottom") if lv.get(k))

    if e["type"] == "breakout":
        head = "🟡 BTC ทะลุขึ้นเหนือ EMA200" if long else "🟡 BTC ทะลุลงใต้ EMA200"
        tail = "รอราคาย่อลงมา..." if long else "รอราคาเด้งขึ้นไป..."
        return (f"{head}\n⏰ {t} (15m)\n💰 ราคา {fmt_price(e['price'])}\n"
                f"EMA100: {fmt_price(e['ema100'])}\nEMA200: {fmt_price(e['ema200'])}\n"
                f"แนว{'รับ' if long else 'ต้าน'}:\n{lines_txt}\n{tail}")
    if e["type"] == "entry":
        head = "🟢 เข้า LONG ได้" if long else "🔴 เข้า SHORT ได้"
        return (f"{head}\n⏰ {t} (15m)\n💰 ราคา {fmt_price(e['price'])}\n"
                f"✅ ยืน{names[e['holding']]}ได้ ({fmt_price(e['holding_price'])})\n"
                f"EMA100: {fmt_price(e['ema100'])}\nEMA200: {fmt_price(e['ema200'])}\n"
                f"แนว{'รับ' if long else 'ต้าน'}:\n{lines_txt}")
    return f"⚪ ยกเลิกสัญญาณ {'LONG' if long else 'SHORT'}: {e['reason']}\n⏰ {t}"


def main():
    dry = "--dry" in sys.argv
    now = int(time.time() * 1000)
    candles = [c for c in fetch_klines(limit=1000) if c[5] < now]  # เฉพาะแท่งที่ปิดแล้ว
    events, _, _ = scan_both(candles, Config())

    state = {}
    if os.path.exists(STATE):
        with open(STATE) as f:
            state = json.load(f)
    last_done = state.get("last_open_time", now - FIRST_RUN_LOOKBACK_MS)

    new = [e for e in events if candles[e["i"]][0] > last_done]
    for e in new:
        text = message(e, candles[e["i"]])
        print(text, "\n")
        if not dry:
            from line_notify import send
            send(text)

    if not new:
        last = candles[-1]
        print(f"ไม่มีสัญญาณใหม่ (แท่งล่าสุด {datetime.fromtimestamp(last[0] / 1000, TH):%d/%m %H:%M} "
              f"ราคา {fmt_price(last[4])})")
    if not dry:
        with open(STATE, "w") as f:
            json.dump({"last_open_time": candles[-1][0]}, f)


if __name__ == "__main__":
    main()
