"""ส่งข้อความเข้า LINE ผ่าน Messaging API (push message)

ต้องมีค่า 2 ตัว (ใส่ในไฟล์ .env บนเครื่อง หรือ GitHub Secrets):
  LINE_CHANNEL_ACCESS_TOKEN
  LINE_USER_ID

ทดสอบ: python line_notify.py
"""
import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path=os.path.join(HERE, ".env")):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def send(text):
    load_env()
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user = os.environ.get("LINE_USER_ID")
    if not token or not user:
        raise SystemExit("ยังไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID (ดู .env.example)")
    body = json.dumps({"to": user, "messages": [{"type": "text", "text": text}]}).encode()
    req = urllib.request.Request("https://api.line.me/v2/bot/message/push", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        raise SystemExit(f"LINE ส่งไม่สำเร็จ ({e.code}): {e.read().decode(errors='replace')}")


if __name__ == "__main__":
    send("✅ ทดสอบ: บอทแจ้งเตือน BTC เชื่อมต่อ LINE สำเร็จ")
    print("ส่งข้อความทดสอบแล้ว เช็คใน LINE ได้เลย")
