"""
media_build.py — real animasiyalı 9:16 video (Pillow + FFmpeg) + TTS.
Fon = mövzuya uyğun REAL Pexels şəkli (image_query ilə). Şəkil tapılmasa/açar
yoxdursa avtomatik gradient fona keçir (fallback). Mətn şəkilə "yandırılır"
(Windows altyazı problemi olmur), hərəkət = zoompan, keçidlər = xfade.
Səs = ElevenLabs (açar varsa) yoxsa gTTS (açarsız).
"""
import os, subprocess, tempfile, textwrap, io
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920
PALETTES = [((16,24,40),(40,90,120)),((30,16,44),(120,40,110)),
            ((12,34,26),(30,140,90)),((34,20,12),(150,90,20))]


def _font(sz):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "C:\\Windows\\Fonts\\arialbd.ttf", "arialbd.ttf"]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, sz)
            except Exception: pass
    return ImageFont.load_default()


# ---------- Pexels: mövzuya uyğun real şəkil ----------
def _fetch_pexels(query, path):
    """query üçün 1 portret foto endirir, path-ə yazır. Uğur=True."""
    key = os.getenv("PEXELS_API_KEY")
    if not key or not query:
        return False
    try:
        import requests
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            params={"query": query, "orientation": "portrait",
                    "per_page": 1, "size": "large"},
            timeout=15)
        if r.status_code != 200:
            return False
        photos = r.json().get("photos", [])
        if not photos:
            return False
        src = photos[0]["src"]
        img_url = src.get("portrait") or src.get("large2x") or src.get("large") or src.get("original")
        img = requests.get(img_url, timeout=20)
        if img.status_code != 200:
            return False
        with open(path, "wb") as f:
            f.write(img.content)
        return True
    except Exception:
        return False


def _cover(img, w, h):
    """Şəkli w x h ölçüsünü tam dolduracaq şəkildə böyüt + mərkəzdən kəs."""
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    nw, nh = int(sw * scale) + 1, int(sh * scale) + 1
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _gradient_bg(pal):
    """Fallback: gradient fon (şəkil tapılmayanda)."""
    c1, c2 = pal
    img = Image.new("RGB", (W, H), c1)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(c1[0]+(c2[0]-c1[0])*t),
              int(c1[1]+(c2[1]-c1[1])*t), int(c1[2]+(c2[2]-c1[2])*t)))
    return img


def _dark_overlay(img):
    """Ağ yazının oxunması üçün şəklin üstünə qaranlıq qat + aşağıda gücləndirilmiş gradient."""
    img = img.convert("RGB")
    ov = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(ov)
    for y in range(H):
        t = y / H
        # üst 90, mərkəz ~120, alt ~200 (aşağıda mətn/altyazı daha çox qaralsın)
        a = int(95 + 120 * (t ** 1.6))
        d.line([(0, y), (W, y)], fill=min(a, 210))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(black, img, ov)


def _scene_png(head, sub, pal, path, image_query=None):
    # 1) fon: əvvəl Pexels şəkli, alınmasa gradient
    bg = None
    if image_query:
        raw = path + ".raw"
        if _fetch_pexels(image_query, raw):
            try:
                bg = _cover(Image.open(raw), W, H)
            except Exception:
                bg = None
            finally:
                try: os.remove(raw)
                except Exception: pass
    if bg is None:
        bg = _gradient_bg(pal)

    # 2) oxunaqlılıq üçün qaranlıq qat
    img = _dark_overlay(bg)
    d = ImageDraw.Draw(img)

    # 3) yazı (kölgə + ağ mətn)
    f = _font(96); fs = _font(46)
    lines = textwrap.wrap((head or "").upper(), width=12) or [""]
    y = H // 2 - len(lines) * 70
    for ln in lines:
        w = d.textlength(ln, font=f)
        x = (W - w) / 2
        d.text((x + 4, y + 4), ln, font=f, fill=(0, 0, 0))      # kölgə
        d.text((x, y), ln, font=f, fill="white")
        y += 120
    if sub:
        w = d.textlength(sub, font=fs)
        x = (W - w) / 2
        d.text((x + 3, y + 33), sub, font=fs, fill=(0, 0, 0))
        d.text((x, y + 30), sub, font=fs, fill=(230, 235, 230))

    img.convert("RGB").save(path)


def _audio_len(path):
    try:
        out = subprocess.check_output(["ffprobe","-v","error","-show_entries",
              "format=duration","-of","default=noprint_wrappers=1:nokey=1", path])
        return float(out.strip())
    except Exception: return 20.0


def build_video(scenes, audio_path=None, out="final.mp4", stills_dir="."):
    real_n = min(len(scenes or []), 4) or 1
    scenes = (scenes or [])[:4]
    while len(scenes) < 4: scenes.append({"headline":"...","sub":""})
    T = 0.6
    total = _audio_len(audio_path) if (audio_path and os.path.exists(audio_path)) else 20.0
    L = max(3.0, (total + 3*T) / 4)
    tmp = tempfile.mkdtemp(); clips = []
    for i, s in enumerate(scenes):
        png = os.path.join(tmp, f"s{i}.png")
        _scene_png(s.get("headline",""), s.get("sub",""), PALETTES[i%4], png,
                   image_query=s.get("image_query"))
        if i < real_n:
            try:
                _im = Image.open(png).convert("RGB"); _im.thumbnail((540, 960))
                _im.save(os.path.join(stills_dir, f"scene_{i+1}.jpg"), quality=82)
            except Exception: pass
        clip = os.path.join(tmp, f"c{i}.mp4")
        subprocess.run(["ffmpeg","-y","-loop","1","-i",png,"-t",str(L),
          "-vf", f"scale=1620:2880,zoompan=z='min(zoom+0.0012,1.18)':d={int(L*25)}:"
          "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=25,format=yuv420p",
          "-c:v","libx264", clip, "-loglevel","error"], check=True)
        clips.append(clip)
    inputs = []
    for c in clips: inputs += ["-i", c]
    # xfade chain: son etiket mütləq [v]
    fc = f"[0][1]xfade=transition=fade:duration={T}:offset={round(1*(L-T),2)}[x1];" \
         f"[x1][2]xfade=transition=fade:duration={T}:offset={round(2*(L-T),2)}[x2];" \
         f"[x2][3]xfade=transition=fade:duration={T}:offset={round(3*(L-T),2)},format=yuv420p[v]"
    # Atomik yazma: əvvəl müvəqqəti fayla yaz, tam bitəndə rename et.
    # Belə polling/oxuma heç vaxt yarımçıq (moov atom-suz) fayl görməz.
    tmp_out = out + ".tmp.mp4"
    cmd = ["ffmpeg","-y"] + inputs
    if audio_path and os.path.exists(audio_path):
        cmd += ["-i", audio_path, "-filter_complex", fc,
                "-map","[v]","-map","4:a","-c:v","libx264","-c:a","aac",
                "-movflags","+faststart","-shortest", tmp_out, "-loglevel","error"]
    else:
        cmd += ["-filter_complex", fc, "-map","[v]","-c:v","libx264",
                "-movflags","+faststart", tmp_out, "-loglevel","error"]
    subprocess.run(cmd, check=True)
    os.replace(tmp_out, out)   # atomik: yalnız tam fayl final.mp4 olur
    return out


def synthesize(text, out="voice.mp3"):
    """ElevenLabs (ELEVENLABS_API_KEY varsa) yoxsa gTTS."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if key:
        import requests
        vid = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
            headers={"xi-api-key": key, "Content-Type":"application/json"},
            json={"text": text, "model_id":"eleven_multilingual_v2"})
        if r.status_code == 200:
            open(out,"wb").write(r.content); return out
    from gtts import gTTS      # pip install gtts (açarsız, internet lazımdır)
    gTTS(text=text, lang="en").save(out); return out