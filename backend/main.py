import os, json, re, datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# --- LCEL: PromptTemplate | LLM | JsonOutputParser ---
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

def get_llm(temperature: float = 0.4):
    provider = os.getenv("LLM_PROVIDER", "google")
    model = os.getenv("LLM_MODEL", "gemini-3.5-flash")
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

# LCEL zənciri: prompt | llm | parser
def ask_json(prompt: str) -> dict:
    template = PromptTemplate.from_template("{prompt}")
    chain = template | get_llm() | JsonOutputParser()
    return chain.invoke({"prompt": prompt})

app = FastAPI(title="AI Content Factory - Demo Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_ALLOWED_MEDIA = re.compile(r"^[\w\-.]+\.(jpg|jpeg|png|mp3|mp4|wav)$", re.I)

@app.get("/media/{name}")
def get_media(name: str):
    safe = os.path.basename(name)
    if _ALLOWED_MEDIA.match(safe) and os.path.exists(safe):
        ext = safe.rsplit(".", 1)[-1].lower()
        mime = {"mp4":"video/mp4","mp3":"audio/mpeg","wav":"audio/wav",
                "jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png"
                }.get(ext, "application/octet-stream")
        return FileResponse(safe, media_type=mime)
    return {"error": "not found"}

import sqlite3
DB_FILE = "factory.db"
PROJECTS_FILE = "projects.json"
STATS_FILE = "stats.json"

def _db():
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; return conn

def _init_db():
    conn = _db()
    conn.execute("""CREATE TABLE IF NOT EXISTS projects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, platform TEXT, video_id TEXT, url TEXT,
        privacy TEXT, status TEXT, created TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS stats(key TEXT PRIMARY KEY, value INTEGER)""")
    for k in ("research_runs","sources_analyzed","videos_created"):
        conn.execute("INSERT OR IGNORE INTO stats(key,value) VALUES(?,0)",(k,))
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"]
    if cnt == 0 and os.path.exists(PROJECTS_FILE):
        try:
            old = json.load(open(PROJECTS_FILE,encoding="utf-8"))
            for rec in reversed(old):
                conn.execute("INSERT INTO projects(title,platform,video_id,url,privacy,status,created) VALUES(?,?,?,?,?,?,?)",
                    (rec.get("title"),rec.get("platform"),rec.get("video_id"),rec.get("url"),rec.get("privacy"),rec.get("status"),rec.get("created")))
            conn.commit()
        except Exception: pass
    if os.path.exists(STATS_FILE):
        try:
            olds = json.load(open(STATS_FILE,encoding="utf-8"))
            for k,v in olds.items():
                cur = conn.execute("SELECT value FROM stats WHERE key=?",(k,)).fetchone()
                if cur is not None and cur["value"]==0 and int(v)>0:
                    conn.execute("UPDATE stats SET value=? WHERE key=?",(int(v),k))
            conn.commit()
        except Exception: pass
    conn.close()

_init_db()

def _read_projects():
    try:
        conn = _db()
        rows = conn.execute("SELECT title,platform,video_id,url,privacy,status,created FROM projects ORDER BY id DESC").fetchall()
        conn.close(); return [dict(r) for r in rows]
    except Exception: return []

def _append_project(rec):
    try:
        conn = _db()
        conn.execute("INSERT INTO projects(title,platform,video_id,url,privacy,status,created) VALUES(?,?,?,?,?,?,?)",
            (rec.get("title"),rec.get("platform"),rec.get("video_id"),rec.get("url"),rec.get("privacy"),rec.get("status"),rec.get("created")))
        conn.commit(); conn.close()
    except Exception: pass

@app.get("/projects")
def list_projects(): return {"projects": _read_projects()}

def _read_stats():
    try:
        conn = _db(); rows = conn.execute("SELECT key,value FROM stats").fetchall(); conn.close()
        s = {r["key"]:r["value"] for r in rows}
        for k in ("research_runs","sources_analyzed","videos_created"): s.setdefault(k,0)
        return s
    except Exception: return {"research_runs":0,"sources_analyzed":0,"videos_created":0}

def _bump_stats(**kw):
    try:
        conn = _db()
        for k,v in kw.items():
            conn.execute("INSERT OR IGNORE INTO stats(key,value) VALUES(?,0)",(k,))
            conn.execute("UPDATE stats SET value=value+? WHERE key=?",(v,k))
        conn.commit(); conn.close()
    except Exception: pass

@app.get("/stats")
def get_stats():
    s = _read_stats(); s["published"] = len(_read_projects()); return s

@app.get("/health")
def health():
    return {"ok":True,"provider":os.getenv("LLM_PROVIDER"),"model":os.getenv("LLM_MODEL")}

@app.get("/connections")
def connections():
    return {"youtube":os.path.exists("token.json"),
            "telegram":bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))}

from research_real import search_sources

class Command(BaseModel):
    command: str
    platforms: list[str] = ["youtube","telegram"]

class ScriptReq(BaseModel):
    topic: str
    duration: int = 45

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
    try: data = ask_json(prompt)
    except Exception as e: data = {"error":str(e),"topics":[]}
    data["sources"] = sources
    _bump_stats(research_runs=1, sources_analyzed=len(sources))
    return data

@app.post("/script")
def script(req: ScriptReq):
    prompt = f'''Write a {req.duration}-second vertical short-form video script about: "{req.topic}".
Return ONLY valid JSON, no markdown:
{{"script":{{"hook":"...","body":"...","why":"...","ending":"..."}},
"scenes":[{{"idx":1,"headline":"SHORT UPPERCASE LINE","image_query":"2-4 concrete English photo keywords","start_sec":0,"end_sec":5}}],
"caption_youtube":"YouTube title-style line (max ~70 chars)",
"description_youtube":"2-3 sentence YouTube description summarizing the video, ending with a call to action",
"caption_telegram":"Short Telegram post caption with 1-2 emojis",
"hashtags":"#tag1 #tag2 #tag3"}}
Rules:
- exactly 4 scenes, covering 0..{req.duration} seconds in order.
- image_query MUST be concrete, photographable English nouns for that scene. Do NOT reuse the headline.
- description_youtube is the longer description text, caption_youtube is the short title.'''
    try: return ask_json(prompt)
    except Exception as e: return {"error":str(e)}

from youtube_upload import upload_short

@app.post("/publish/youtube")
def publish_youtube(payload: dict):
    title = payload.get("title","AI Content Factory")
    desc = payload.get("description","")
    privacy = payload.get("privacy","private")
    try:
        try: vid = upload_short("final.mp4",title,desc,privacy=privacy)
        except TypeError: vid = upload_short("final.mp4",title,desc)
        url = f"https://studio.youtube.com/video/{vid}/edit"
        _append_project({"title":title,"platform":"YouTube","video_id":vid,"url":url,
                          "privacy":privacy,"status":"Published","created":datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
        return {"ok":True,"video_id":vid,"url":url,"privacy":privacy}
    except Exception as e: return {"ok":False,"error":str(e)}

@app.post("/publish/telegram")
def publish_telegram(payload: dict):
    import requests
    token = os.getenv("TELEGRAM_TOKEN"); chat_id = os.getenv("TELEGRAM_CHAT_ID")
    caption = payload.get("caption") or payload.get("title") or "AI Content Factory"
    if not token or not chat_id:
        return {"ok":False,"error":"TELEGRAM_TOKEN / TELEGRAM_CHAT_ID .env-də yoxdur"}
    if not os.path.exists("final.mp4"):
        return {"ok":False,"error":"final.mp4 tapılmadı — əvvəl video yarat"}
    try:
        with open("final.mp4","rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo",
                data={"chat_id":chat_id,"caption":caption[:1024]},
                files={"video":("final.mp4",f,"video/mp4")}, timeout=180)
        j = r.json()
        if not j.get("ok"): return {"ok":False,"error":j.get("description","Telegram API xətası")}
        mid = j["result"]["message_id"]
        _append_project({"title":caption[:80],"platform":"Telegram","video_id":str(mid),
                          "url":"","privacy":"chat","status":"Published",
                          "created":datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
        return {"ok":True,"message_id":mid}
    except Exception as e: return {"ok":False,"error":str(e)}

from media_build import build_video, synthesize

class ProduceReq(BaseModel):
    narration: str
    scenes: list = []

@app.post("/produce")
def produce(req: ProduceReq):
    try:
        synthesize(req.narration,"voice.mp3")
        raw = req.scenes or []
        scenes = [{"headline":s.get("headline",""),"sub":"","image_query":s.get("image_query","")} for s in raw]
        build_video(scenes or [{"headline":"AI"}],"voice.mp3","final.mp4",stills_dir=".")
        _bump_stats(videos_created=1)
        n = min(len(raw),4) or 1
        scene_meta = [{"headline":(raw[i] if i<len(raw) else {}).get("headline",""),
                        "image":f"scene_{i+1}.jpg",
                        "start_sec":(raw[i] if i<len(raw) else {}).get("start_sec"),
                        "end_sec":(raw[i] if i<len(raw) else {}).get("end_sec")} for i in range(n)]
        return {"ok":True,"video":"final.mp4","audio":"voice.mp3","scenes":scene_meta}
    except Exception as e: return {"ok":False,"error":str(e)}