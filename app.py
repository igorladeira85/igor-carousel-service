from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests
import base64

app = Flask(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = (9, 9, 20)
GOLD      = (242, 185, 30)
GOLD_DIM  = (90, 68, 10)
WHITE     = (238, 238, 248)
MUTED     = (140, 140, 165)

# ── Fonts (Poppins bundled in /fonts) ────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_FD   = os.path.join(_HERE, "fonts")
F_BOLD = os.path.join(_FD, "Poppins-Bold.ttf")
F_SEMI = os.path.join(_FD, "Poppins-Medium.ttf")
F_REG  = os.path.join(_FD, "Poppins-Regular.ttf")
F_LITE = os.path.join(_FD, "Poppins-Light.ttf")


def fnt(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def draw_text_wrapped(draw, text, x, y, max_width, font, fill, line_spacing=12):
    """Wraps text to fit max_width pixels. Returns final y position."""
    words = text.split()
    lines = []
    current = ""
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


def generate_slide(title, body, slide_num, total_slides, handle="@igorladeira85"):
    W, H = 1080, 1080
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    PAD   = 80    # outer padding
    INNER = 116   # content x start (after accent bar)

    # ── Left gold accent bar ──────────────────────────────────────────────────
    draw.rectangle([(PAD, PAD), (PAD + 8, H - PAD)], fill=GOLD)

    # ── Top-right: slide counter ──────────────────────────────────────────────
    f_counter = fnt(F_SEMI, 28)
    counter   = f"{slide_num} / {total_slides}"
    cb = draw.textbbox((0, 0), counter, font=f_counter)
    draw.text((W - PAD - (cb[2] - cb[0]), PAD + 8), counter, fill=GOLD, font=f_counter)

    # ── Subtle top divider ────────────────────────────────────────────────────
    draw.rectangle([(INNER, PAD + 44), (W - PAD, PAD + 47)], fill=GOLD_DIM)

    # ── Title ─────────────────────────────────────────────────────────────────
    f_title  = fnt(F_BOLD, 76)
    TEXT_W   = W - INNER - PAD
    y        = PAD + 90

    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, GOLD, line_spacing=10)
    y += 28

    # ── Gold accent dash ──────────────────────────────────────────────────────
    draw.rectangle([(INNER, y), (INNER + 72, y + 5)], fill=GOLD)
    y += 44

    # ── Body ──────────────────────────────────────────────────────────────────
    f_body = fnt(F_REG, 38)
    y = draw_text_wrapped(draw, body, INNER, y, TEXT_W, f_body, WHITE, line_spacing=14)

    # ── Bottom area ───────────────────────────────────────────────────────────
    f_handle = fnt(F_SEMI, 28)
    draw.rectangle([(INNER, H - PAD - 52), (INNER + 220, H - PAD - 49)], fill=GOLD_DIM)
    draw.text((INNER, H - PAD - 38), handle, fill=MUTED, font=f_handle)

    return img


@app.route("/generate", methods=["POST"])
def generate():
    data      = request.get_json(force=True)
    title     = data.get("title", "")
    body      = data.get("body", "")
    slide_num = int(data.get("slide_num", 1))
    total     = int(data.get("total_slides", 1))
    imgbb_key = data.get("imgbb_key", "")

    img = generate_slide(title, body, slide_num, total)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    buf.seek(0)

    if imgbb_key:
        b64  = base64.b64encode(buf.read()).decode("utf-8")
        resp = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": imgbb_key, "image": b64, "expiration": 604800},
        )
        if resp.ok:
            return jsonify({"url": resp.json()["data"]["url"], "status": "ok"})
        return jsonify({"error": "ImgBB upload falhou", "detail": resp.text}), 500

    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


@app.route("/run_workflow", methods=["POST"])
def run_workflow():
    import re, time
    data       = request.get_json(force=True)
    date_str   = data.get("date")          # "YYYY-MM-DD"
    gh_token   = data.get("gh_token")
    ig_token   = data.get("ig_token")
    ig_user_id = data.get("ig_user_id")
    imgbb_key  = data.get("imgbb_key")

    # 1. Lista arquivos na pasta instagram
    list_url = "https://api.github.com/repos/igorladeira85/igor-vault/contents/06%20projetos%2Fpersona-digital%2Finstagram"
    gh_headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
    files = requests.get(list_url, headers=gh_headers).json()
    match = next((f for f in files if f["name"].startswith(date_str)), None)
    if not match:
        return jsonify({"error": f"Nenhum arquivo para {date_str}"}), 404

    # 2. Lê conteúdo do arquivo
    file_resp = requests.get(match["url"], headers=gh_headers).json()
    decoded   = base64.b64decode(file_resp["content"]).decode("utf-8")

    # 3. Parse frontmatter e slides
    content, caption = decoded, ""
    if content.startswith("---"):
        end = content.index("---", 3)
        fm  = content[3:end]
        cap = re.search(r"caption:\s*(.+)", fm)
        if cap:
            caption = cap.group(1).strip()
        content = content[end + 3:].strip()

    slides = []
    for section in content.split("\n---\n"):
        t = section.strip()
        if not t:
            continue
        tm = re.search(r"\*\*T[ií]tulo:\*\*\s*(.+)", t, re.I)
        bm = re.search(r"\*\*Texto:\*\*\s*([\s\S]+)", t, re.I)
        if tm:
            slides.append({"title": tm.group(1).strip(), "body": re.sub(r"\n+", " ", bm.group(1).strip()) if bm else ""})

    if not slides:
        return jsonify({"error": "Nenhum slide encontrado"}), 400
    if not caption:
        caption = slides[0]["title"]

    # 4. Gera imagens e cria containers Instagram
    ig_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {ig_token}"}
    container_ids = []
    for i, slide in enumerate(slides):
        img = generate_slide(slide["title"], slide["body"], i + 1, len(slides))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("utf-8")
        up  = requests.post("https://api.imgbb.com/1/upload", data={"key": imgbb_key, "image": b64, "expiration": 604800})
        if not up.ok:
            return jsonify({"error": f"ImgBB slide {i+1}", "detail": up.text}), 500
        img_url = up.json()["data"]["url"]

        ig = requests.post(f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
                           headers=ig_headers,
                           json={"image_url": img_url, "is_carousel_item": True})
        ig_data = ig.json()
        if "id" not in ig_data:
            return jsonify({"error": f"Container slide {i+1}", "detail": ig_data}), 500
        container_ids.append(ig_data["id"])

    # 5. Cria carrossel
    car = requests.post(f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
                        headers=ig_headers,
                        json={"media_type": "CAROUSEL", "children": ",".join(container_ids), "caption": caption})
    car_data = car.json()
    if "id" not in car_data:
        return jsonify({"error": "Criar carrossel", "detail": car_data}), 500

    # 6. Aguarda processamento
    time.sleep(30)

    # 7. Publica
    pub = requests.post(f"https://graph.instagram.com/v21.0/{ig_user_id}/media_publish",
                        headers=ig_headers,
                        json={"creation_id": car_data["id"]})
    pub_data = pub.json()
    return jsonify({"status": "publicado", "post_id": pub_data.get("id"), "slides": len(slides), "caption": caption})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
