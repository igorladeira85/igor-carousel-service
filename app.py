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


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
