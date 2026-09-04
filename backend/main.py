import os, json, re, datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# --- Provider-agnostic LLM (arxitektura "wow"u: model koda bağlı deyil) ---
def get_llm(temperature: float = 0.4):
    provider = os.getenv("LLM_PROVIDER", "google")
    model = os.getenv("LLM_MODEL", "gemini-3.5-flash")  # 2.0/2.5-flash bağlanıb
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model, temperature=temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY"))
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=temperature,
                          api_key=os.getenv("OPENAI_API_KEY"))
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

def _to_text(content):
    # Gemini 3.x .content bəzən list qaytarır -> mətnə çevir
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                out.append(part.get("text", ""))
        return "".join(out)
    return str(content)

def ask_json(prompt: str):
    raw = _to_text(get_llm().invoke(prompt).content).strip()
    raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)

app = FastAPI(title="AI Content Factory - Demo Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# --- Media serve: səhnə şəkilləri, voice.mp3, final.mp4 (Content Studio üçün) ---
_ALLOWED_MEDIA = re.compile(r"^[\w\-.]+\.(jpg|jpeg|png|mp3|mp4|wav)$", re.I)

@app.get("/media/{name}")
def get_media(name: str):
    safe = os.path.basename(name)          # path traversal-ı bağla
    if _ALLOWED_MEDIA.match(safe) and os.path.exists(safe):
        return FileResponse(safe)
    return {"error": "not found"}

# --- Persistence: SQLite (real DB). Köhnə JSON varsa avtomatik köçürülür. ---
import sqlite3

DB_FILE = "factory.db"
PROJECTS_FILE = "projects.json"   # köhnə data (migrasiya üçün)
STATS_FILE = "stats.json"

def _db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db():
    conn = _db()
    conn.execute("""CREATE TABLE IF NOT EXISTS projects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, platform TEXT, video_id TEXT, url TEXT,
        privacy TEXT, status TEXT, created TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS stats(
        key TEXT PRIMARY KEY, value INTEGER)""")
    for k in ("research_runs", "sources_analyzed", "videos_created"):
        conn.execute("INSERT OR IGNORE INTO stats(key, value) VALUES(?, 0)", (k,))
    conn.commit()
    # --- Bir dəfəlik migrasiya: köhnə projects.json → DB ---
    cnt = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"]
    if cnt == 0 and os.path.exists(PROJECTS_FILE):
        try:
            with open(PROJECTS_FILE, encoding="utf-8") as f:
                old = json.load(f)
            # köhnə fayl yenidən-köhnəyə (newest first) yazılıb; DB-yə tərsinə əlavə edək ki, id sırası düz olsun
            for rec in reversed(old):
                conn.execute("""INSERT INTO projects(title,platform,video_id,url,privacy,status,created)
                    VALUES(?,?,?,?,?,?,?)""",
                    (rec.get("title"), rec.get("platform"), rec.get("video_id"),
                     rec.get("url"), rec.get("privacy"), rec.get("status"), rec.get("created")))
            conn.commit()
        except Exception:
            pass
    # köhnə stats.json → DB
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                olds = json.load(f)
            for k, v in olds.items():
                cur = conn.execute("SELECT value FROM stats WHERE key=?", (k,)).fetchone()
                if cur is not None and cur["value"] == 0 and int(v) > 0:
                    conn.execute("UPDATE stats SET value=? WHERE key=?", (int(v), k))
            conn.commit()
        except Exception:
            pass
    conn.close()

_init_db()

def _read_projects():
    try:
        conn = _db()
        rows = conn.execute("""SELECT title,platform,video_id,url,privacy,status,created
                               FROM projects ORDER BY id DESC""").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def _append_project(rec):
    try:
        conn = _db()
        conn.execute("""INSERT INTO projects(title,platform,video_id,url,privacy,status,created)
            VALUES(?,?,?,?,?,?,?)""",
            (rec.get("title"), rec.get("platform"), rec.get("video_id"),
             rec.get("url"), rec.get("privacy"), rec.get("status"), rec.get("created")))
        conn.commit()
        conn.close()
    except Exception:
        pass

@app.get("/projects")
def list_projects():
    return {"projects": _read_projects()}

def _read_stats():
    try:
        conn = _db()
        rows = conn.execute("SELECT key, value FROM stats").fetchall()
        conn.close()
        s = {r["key"]: r["value"] for r in rows}
        for k in ("research_runs", "sources_analyzed", "videos_created"):
            s.setdefault(k, 0)
        return s
    except Exception:
        return {"research_runs": 0, "sources_analyzed": 0, "videos_created": 0}

def _bump_stats(**kw):
    try:
        conn = _db()
        for k, v in kw.items():
            conn.execute("INSERT OR IGNORE INTO stats(key, value) VALUES(?, 0)", (k,))
            conn.execute("UPDATE stats SET value = value + ? WHERE key = ?", (v, k))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return _read_stats()

@app.get("/stats")
def get_stats():
    s = _read_stats()
    s["published"] = len(_read_projects())
    return s

class Command(BaseModel):
    command: str
    platforms: list[str] = ["youtube", "instagram-reel"]

class ScriptReq(BaseModel):
    topic: str
    duration: int = 45

@app.get("/health")
def health():
    return {"ok": True, "provider": os.getenv("LLM_PROVIDER"),
            "model": os.getenv("LLM_MODEL")}

# 1) RESEARCH → 3 mövzu tövsiyəsi (Approval #1 üçün)
from research_real import search_sources

@app.post("/research")
def research(cmd: Command):
    sources = search_sources(cmd.command, 6)
    src_text = "\n".join(f"- {s['title']}: {s['snippet']}" for s in sources) or "(no live sources)"
    prompt = f'''You are a research engine for a short-form video factory.
User command: "{cmd.command}"
Real web sources found:
{src_text}
Based on these, suggest 3 specific timely topics. Return ONLY valid JSON:
{{"topics":[{{"title":"...","score":0,"sources_count":0,"is_recommended":false,"why":"one sentence"}}]}}
Exactly one topic has is_recommended=true.'''
    try:
        data = ask_json(prompt)
    except Exception as e:
        data = {"error": str(e), "topics": []}
    data["sources"] = sources
    _bump_stats(research_runs=1, sources_analyzed=len(sources))
    return data

# 2) SCRIPT → skript + 4 səhnə (image_query) + caption + AYRICA youtube description
@app.post("/script")
def script(req: ScriptReq):
    prompt = f'''Write a {req.duration}-second vertical short-form video script about: "{req.topic}".
Return ONLY valid JSON, no markdown:
{{"script":{{"hook":"...","body":"...","why":"...","ending":"..."}},
"scenes":[{{"idx":1,"headline":"SHORT UPPERCASE LINE","image_query":"2-4 concrete English photo keywords","start_sec":0,"end_sec":5}}],
"caption_youtube":"YouTube title-style line (max ~70 chars)",
"description_youtube":"2-3 sentence YouTube description summarizing the video, ending with a call to action",
"caption_instagram":"Instagram caption with 1-2 emojis",
"hashtags":"#tag1 #tag2 #tag3"}}
Rules:
- exactly 4 scenes, covering 0..{req.duration} seconds in order.
- image_query MUST be concrete, photographable English nouns for that scene
  (e.g. "robot arm factory", "person coding dark room"). Do NOT reuse the headline. No abstract words.
- description_youtube is different from caption_youtube: caption_youtube is the short title,
  description_youtube is the longer description text.'''
    try:
        return ask_json(prompt)
    except Exception as e:
        return {"error": str(e)}

from youtube_upload import upload_short

@app.post("/publish/youtube")
def publish_youtube(payload: dict):
    title = payload.get("title", "AI Content Factory")
    desc = payload.get("description", "")
    privacy = payload.get("privacy", "private")   # public / unlisted / private
    try:
        # youtube_upload.py yenilənibsə privacy ötürülür; yenilənməyibsə köhnə imza ilə işləyir
        try:
            vid = upload_short("final.mp4", title, desc, privacy=privacy)
        except TypeError:
            vid = upload_short("final.mp4", title, desc)
        url = f"https://studio.youtube.com/video/{vid}/edit"
        _append_project({
            "title": title,
            "platform": "YouTube",
            "video_id": vid,
            "url": url,
            "privacy": privacy,
            "status": "Published",
            "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        return {"ok": True, "video_id": vid, "url": url, "privacy": privacy}
    except Exception as e:
        return {"ok": False, "error": str(e)}

from media_build import build_video, synthesize

class ProduceReq(BaseModel):
    narration: str
    scenes: list = []

# Real animasiyalı video + TTS (fon = mövzuya uyğun real Pexels şəkli)
@app.post("/produce")
def produce(req: ProduceReq):
    try:
        synthesize(req.narration, "voice.mp3")
        raw = req.scenes or []
        scenes = [{"headline": s.get("headline", ""),
                   "sub": "",
                   "image_query": s.get("image_query", "")}
                  for s in raw]
        build_video(scenes or [{"headline": "AI"}], "voice.mp3", "final.mp4", stills_dir=".")
        _bump_stats(videos_created=1)
        # Content Studio üçün səhnə meta (real şəkil adları ilə)
        n = min(len(raw), 4) or 1
        scene_meta = []
        for i in range(n):
            s = raw[i] if i < len(raw) else {}
            scene_meta.append({
                "headline": s.get("headline", ""),
                "image": f"scene_{i+1}.jpg",
                "start_sec": s.get("start_sec"),
                "end_sec": s.get("end_sec"),
            })
        return {"ok": True, "video": "final.mp4", "audio": "voice.mp3", "scenes": scene_meta}
    except Exception as e:
        return {"ok": False, "error": str(e)}