"""
Instagram Reels publish — container flow (öz hesabına, APP REVIEW-SUZ).

Ön şərtlər (bir dəfəlik, ~yarım-bir gün):
  1. Instagram hesabını Professional (Business/Creator) et:
     Settings → Account type and tools → Switch to professional account.
  2. developers.facebook.com → Create App → use case: Instagram (Instagram Login).
     >>> "Instagram Login" yolu = Facebook Page LAZIM DEYİL. <<<
  3. App Roles → Add People → "Instagram Tester" → öz IG hesabını əlavə et,
     SONRA Instagram app-ında (Settings → Website permissions/Apps) dəvəti QƏBUL et.
  4. Instagram Login ilə OAuth → long-lived token (~60 gün) + ig-user-id al.
  5. App Development mode-da qalsın — review-a getmə (öz hesabın üçün lazım deyil).

VACİB FƏRQ (YouTube-dan): burada video FAYLI yox, videonun PUBLIC URL-i göndərilir.
Meta serverləri videonu o URL-dən ÖZÜ çəkir. Deməli MP4 ictimai host olunmalıdır:
  - Production: DigitalOcean Spaces / S3 public bucket
  - Demo (ən sürətli): `cloudflared tunnel --url http://localhost:8000` və ya ngrok
Reels tələbləri sərtdir (MP4 / H.264 / AAC / 9:16) — səhv fayl aydın xəta yox,
"failed container" verir.

İstifadə:
  IG_USER_ID=123 IG_ACCESS_TOKEN=xxx python instagram_upload.py \
      "https://public-host/final.mp4" "AI agents can act 🤖 #AI #reels"
"""
import os, time, sys, requests

# Instagram Login yolu:  https://graph.instagram.com/v21.0
# Facebook Login (Page) yolu:  https://graph.facebook.com/v21.0
# Cari API versiyasını rəsmi sənəddən təsdiqlə.
BASE = os.getenv("IG_API_BASE", "https://graph.facebook.com/v21.0")
IG_USER_ID = os.getenv("IG_USER_ID")
TOKEN = os.getenv("IG_ACCESS_TOKEN")

def publish_reel(video_url: str, caption: str) -> str:
    # 1) media container yarat
    r = requests.post(f"{BASE}/{IG_USER_ID}/media", data={
        "media_type": "REELS", "video_url": video_url,
        "caption": caption, "access_token": TOKEN}).json()
    if "id" not in r:
        raise RuntimeError(f"Container error: {r}")
    creation_id = r["id"]

    # 2) video emalı bitənə qədər gözlə (async)
    for _ in range(30):
        s = requests.get(f"{BASE}/{creation_id}", params={
            "fields": "status_code", "access_token": TOKEN}).json()
        code = s.get("status_code")
        print("status:", code)
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"Processing failed: {s}")
        time.sleep(5)
    else:
        raise TimeoutError("Container did not finish in time")

    # 3) publish et
    p = requests.post(f"{BASE}/{IG_USER_ID}/media_publish", data={
        "creation_id": creation_id, "access_token": TOKEN}).json()
    if "id" not in p:
        raise RuntimeError(f"Publish error: {p}")
    print("Published Reel id:", p["id"])
    return p["id"]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: IG_USER_ID=.. IG_ACCESS_TOKEN=.. '
              'python instagram_upload.py <public_video_url> [caption]')
        sys.exit(1)
    url = sys.argv[1]
    cap = sys.argv[2] if len(sys.argv) > 2 else "AI agents can act 🤖 #AI #reels"
    publish_reel(url, cap)