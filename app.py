from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests
import base64

app = Flask(__name__)

# ── Fonts ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_FD   = os.path.join(_HERE, "fonts")
F_PF  = os.path.join(_FD, "PlayfairDisplay.ttf")   # variable font

# Weight constants
W_BLACK  = 900
W_BOLD   = 700
W_REGULAR = 400


def fnt(path, size, weight=400):
    try:
        font = ImageFont.truetype(path, size)
        try:
            font.set_variation_by_axes({"wght": weight})
        except Exception:
            pass
        return font
    except Exception:
        return ImageFont.load_default()


def draw_text_wrapped(draw, text, x, y, max_width, font, fill, line_spacing=12):
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        bbox = draw.textbbox((0, 0), line, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing
    return y


def generate_slide(title, body, slide_num, total_slides,
                   style="escuro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1080

    # ── Theme ──────────────────────────────────────────────────────────────────
    if style == "claro":
        BG       = (245, 240, 232)
        ACCENT   = (232, 82,  10)
        DIM      = (212, 200, 176)
        TITLE_C  = (26,  26,  26)
        BODY_C   = (26,  26,  26)
        MUTED    = (140, 128, 106)
        SIG_C    = (176, 164, 140)
        WM_C     = (232, 227, 216)
        TAG_BG   = (232, 82,  10)
        TAG_FG   = (245, 240, 232)
    else:  # escuro
        BG       = (9,   9,   26)
        ACCENT   = (242, 185, 30)
        DIM      = (90,  68,  10)
        TITLE_C  = (238, 238, 248)
        BODY_C   = (238, 238, 248)
        MUTED    = (140, 140, 165)
        SIG_C    = (90,  68,  10)
        WM_C     = (20,  20,  48)
        TAG_BG   = (242, 185, 30)
        TAG_FG   = (9,   9,   26)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    PAD   = 80
    INNER = 122   # after accent bar + gap

    # ── Left accent bar ────────────────────────────────────────────────────────
    draw.rectangle([(PAD, PAD), (PAD + 5, H - PAD)], fill=ACCENT)

    # ── Top horizontal rule ───────────────────────────────────────────────────
    draw.rectangle([(INNER, 100), (W - PAD, 101)], fill=DIM)

    # ── Macrotema tag ─────────────────────────────────────────────────────────
    y = 210
    if macrotema:
        f_tag = fnt(F_PF, 22, W_BOLD)
        tb     = draw.textbbox((0, 0), macrotema, font=f_tag)
        tag_w  = tb[2] - tb[0] + 28
        draw.rectangle([(INNER, 118), (INNER + tag_w, 150)], fill=TAG_BG)
        draw.text((INNER + 14, 124), macrotema, fill=TAG_FG, font=f_tag)
        y = 220

    # ── Watermark slide number ────────────────────────────────────────────────
    f_wm = fnt(F_PF, 340, W_BLACK)
    wm   = str(slide_num)
    wb   = draw.textbbox((0, 0), wm, font=f_wm)
    wm_w = wb[2] - wb[0]
    wm_h = wb[3] - wb[1]
    draw.text((W - PAD - wm_w + 30, H - PAD - wm_h + 60), wm, fill=WM_C, font=f_wm)

    # ── Title ──────────────────────────────────────────────────────────────────
    f_title = fnt(F_PF, 88, W_BOLD)
    TEXT_W  = W - INNER - PAD
    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, ACCENT, line_spacing=6)
    y += 28

    # ── Accent dash ───────────────────────────────────────────────────────────
    draw.rectangle([(INNER, y), (INNER + 64, y + 4)], fill=ACCENT)
    y += 48

    # ── Body ──────────────────────────────────────────────────────────────────
    if body:
        f_body = fnt(F_PF, 40, W_REGULAR)
        draw_text_wrapped(draw, body, INNER, y, TEXT_W, f_body, BODY_C, line_spacing=14)

    # ── Bottom rule + signature ───────────────────────────────────────────────
    draw.rectangle([(INNER, H - PAD - 54), (W - PAD, H - PAD - 53)], fill=DIM)
    f_sig = fnt(F_PF, 26, W_REGULAR)
    draw.text((INNER, H - PAD - 36), handle, fill=SIG_C, font=f_sig)

    return img


@app.route("/generate", methods=["POST"])
def generate():
    data      = request.get_json(force=True)
    title     = data.get("title", "")
    body      = data.get("body", "")
    slide_num = int(data.get("slide_num", 1))
    total     = int(data.get("total_slides", 1))
    style     = data.get("style", "escuro")
    macrotema = data.get("macrotema", "")
    imgbb_key = data.get("imgbb_key", "")

    img = generate_slide(title, body, slide_num, total, style, macrotema)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    buf.seek(0)

    if imgbb_key:
        b64  = base64.b64encode(buf.read()).decode("utf-8")
        resp = requests.post("https://api.imgbb.com/1/upload",
                             data={"key": imgbb_key, "image": b64, "expiration": 604800})
        if resp.ok:
            return jsonify({"url": resp.json()["data"]["url"], "status": "ok"})
        return jsonify({"error": "ImgBB upload falhou", "detail": resp.text}), 500

    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


_jobs = {}


def _do_workflow(job_id, date_str, gh_token, ig_token, ig_user_id, imgbb_key):
    import re, time
    try:
        list_url   = "https://api.github.com/repos/igorladeira85/igor-vault/contents/06%20projetos%2Fpersona-digital%2Finstagram"
        gh_headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
        files      = requests.get(list_url, headers=gh_headers).json()
        match      = next((f for f in files if f["name"].startswith(date_str)), None)
        if not match:
            _jobs[job_id] = {"status": "error", "error": f"Nenhum arquivo para {date_str}"}
            return

        file_resp = requests.get(match["url"], headers=gh_headers).json()
        decoded   = base64.b64decode(file_resp["content"]).decode("utf-8")

        # ── Parse frontmatter ─────────────────────────────────────────────────
        content, caption, style, macrotema = decoded, "", "escuro", ""
        if content.startswith("---"):
            end = content.index("---", 3)
            fm  = content[3:end]
            cap = re.search(r"caption:\s*(.+)", fm)
            if cap:
                caption = cap.group(1).strip()
            est = re.search(r"estilo:\s*(.+)", fm)
            if est:
                style = est.group(1).strip()
            mac = re.search(r"macrotema:\s*(.+)", fm)
            if mac:
                macrotema = mac.group(1).strip()
            content = content[end + 3:].strip()

        # ── Parse slides ──────────────────────────────────────────────────────
        slides = []
        for section in content.split("\n---\n"):
            t  = section.strip()
            if not t:
                continue
            tm = re.search(r"\*\*T[ií]tulo:\*\*\s*(.+)", t, re.I)
            bm = re.search(r"\*\*Texto:\*\*\s*([\s\S]+)", t, re.I)
            if tm:
                slides.append({
                    "title": tm.group(1).strip(),
                    "body":  re.sub(r"\n+", " ", bm.group(1).strip()) if bm else ""
                })

        if not slides:
            _jobs[job_id] = {"status": "error", "error": "Nenhum slide encontrado"}
            return
        if not caption:
            caption = slides[0]["title"]

        # ── Gera imagens + containers Instagram ───────────────────────────────
        ig_headers   = {"Content-Type": "application/json", "Authorization": f"Bearer {ig_token}"}
        container_ids = []
        for i, slide in enumerate(slides):
            _jobs[job_id]["step"] = f"slide {i+1}/{len(slides)}"
            img = generate_slide(slide["title"], slide["body"],
                                 i + 1, len(slides), style, macrotema if i == 0 else "")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            buf.seek(0)
            b64 = base64.b64encode(buf.read()).decode("utf-8")
            up  = requests.post("https://api.imgbb.com/1/upload",
                                data={"key": imgbb_key, "image": b64, "expiration": 604800})
            if not up.ok:
                _jobs[job_id] = {"status": "error", "error": f"ImgBB slide {i+1}", "detail": up.text}
                return
            img_url = up.json()["data"]["url"]

            ig = requests.post(f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
                               headers=ig_headers,
                               json={"image_url": img_url, "is_carousel_item": True})
            ig_data = ig.json()
            if "id" not in ig_data:
                _jobs[job_id] = {"status": "error", "error": f"Container slide {i+1}", "detail": ig_data}
                return
            container_ids.append(ig_data["id"])

        # ── Carrossel ─────────────────────────────────────────────────────────
        _jobs[job_id]["step"] = "criando carrossel"
        car = requests.post(f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
                            headers=ig_headers,
                            json={"media_type": "CAROUSEL",
                                  "children": ",".join(container_ids),
                                  "caption": caption})
        car_data = car.json()
        if "id" not in car_data:
            _jobs[job_id] = {"status": "error", "error": "Criar carrossel", "detail": car_data}
            return

        # ── Aguarda + publica ─────────────────────────────────────────────────
        _jobs[job_id]["step"] = "aguardando Instagram processar"
        time.sleep(30)
        _jobs[job_id]["step"] = "publicando"
        pub = requests.post(f"https://graph.instagram.com/v21.0/{ig_user_id}/media_publish",
                            headers=ig_headers,
                            json={"creation_id": car_data["id"]})
        pub_data = pub.json()
        _jobs[job_id] = {"status": "publicado", "post_id": pub_data.get("id"),
                         "slides": len(slides), "caption": caption, "style": style}

    except Exception as e:
        _jobs[job_id] = {"status": "error", "error": str(e)}


@app.route("/run_workflow", methods=["POST"])
def run_workflow():
    import threading, time
    data       = request.get_json(force=True)
    date_str   = data.get("date")
    gh_token   = data.get("gh_token")
    ig_token   = data.get("ig_token")
    ig_user_id = data.get("ig_user_id")
    imgbb_key  = data.get("imgbb_key")

    job_id = str(int(time.time()))
    _jobs[job_id] = {"status": "running", "step": "iniciando"}
    t = threading.Thread(target=_do_workflow,
                         args=(job_id, date_str, gh_token, ig_token, ig_user_id, imgbb_key),
                         daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "status": "started"})


@app.route("/status/<job_id>")
def job_status(job_id):
    return jsonify(_jobs.get(job_id, {"status": "not_found"}))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
