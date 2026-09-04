"""
YouTube Shorts upload — real Data API v3 upload (OAuth).

Ön şərtlər (bir dəfəlik, ~yarım gün):
  1. Google Cloud Console → yeni layihə → "YouTube Data API v3"-ü enable et.
  2. OAuth consent screen → User type: External → Testing rejimi →
     "Test users"-a öz Google hesabını əlavə et. Scope: .../auth/youtube.upload
  3. Credentials → Create → OAuth client ID → Application type: "Desktop app".
  4. JSON-u yüklə, bu qovluqda "client_secret.json" adı ilə saxla.
  5. pip install google-auth google-auth-oauthlib google-api-python-client

İstifadə (əvvəlcə video hazırla, sonra):
  python youtube_upload.py final.mp4 "My AI Short" "AI agents can act."

QEYD: Unverified layihədən upload olunan video Google tərəfindən PRIVATE
kilidlənəcək (audit-ə qədər). Bu, koddan deyil, Google siyasətindəndir.
Testing rejimində refresh token ~7 gün sonra bitir — demo üçün problem deyil.
"""
import os, sys
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = "token.json"
CLIENT_SECRET = "client_secret.json"

def _service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=8765)   # brauzeri bir dəfə açır
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload_short(path, title, description, privacy="private", tags=None):
    yt = _service()
    body = {
        "snippet": {"title": title, "description": description + "\n\n#Shorts",
                    "tags": tags or ["Shorts", "AI"], "categoryId": "28"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(path, chunksize=-1, resumable=True, mimetype="video/*")
    resp = yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    vid = resp["id"]
    print(f"Uploaded (privacy={privacy}): https://studio.youtube.com/video/{vid}/edit")
    return vid

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python youtube_upload.py <video.mp4> <title> [description]")
        sys.exit(1)
    path, title = sys.argv[1], sys.argv[2]
    desc = sys.argv[3] if len(sys.argv) > 3 else ""
    upload_short(path, title, desc)