from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import io
import textwrap
import os
import requests
import base64

app = Flask(__name__)

BG_COLOR    = (14, 14, 24)
YELLOW      = (255, 215, 0)
WHITE       = (210, 210, 220)
GRAY        = (120, 120, 145)

BOLD_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG_FONT  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def get_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def generate_slide(title, body, slide_num, total_slides, handle="@igorladeira85"):
    W, H = 1080, 1080
    img  = Image.new("RGB", (W, H), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    f_counter = get_font(REG_FONT,  28)
    f_title   = get_font(BOLD_FONT, 56)
    f_body    = get_font(REG_FONT,  36)
    f_handle  = get_font(REG_FONT,  26)

    M = 72

    draw.rectangle([(M, 70), (W - M, 78)], fill=YELLOW)
    draw.text((M, 92), f"{slide_num} / {total_slides}", fill=YELLOW, font=f_counter)

    y = 165
    wrapped_title = textwrap.fill(title, width=22)
    for line in wrapped_title.split("\n"):
        draw.text((M, y), line, fill=YELLOW, font=f_title)
        bbox = draw.textbbox((0, 0), line, font=f_title)
        y += (bbox[3] - bbox[1]) + 8
    y += 18

    draw.rectangle([(M, y), (M + 110, y + 5)], fill=YELLOW)
    y += 34

    wrapped_body = textwrap.fill(body, width=38)
    for line in wrapped_body.split("\n"):
        draw.text((M, y), line, fill=WHITE, font=f_body)
        bbox = draw.textbbox((0, 0), line, font=f_body)
        y += (bbox[3] - bbox[1]) + 9

    draw.rectangle([(M, H - 88), (W - M, H - 80)], fill=YELLOW)
    draw.text((M, H - 70), handle, fill=GRAY, font=f_handle)

    return img


@app.route("/generate", methods=["POST"])
def generate():
    data        = request.get_json(force=True)
    title       = data.get("title", "")
    body        = data.get("body", "")
    slide_num   = int(data.get("slide_num", 1))
    total       = int(data.get("total_slides", 1))
    imgbb_key   = data.get("imgbb_key", "")

    img = generate_slide(title, body, slide_num, total)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)

    if imgbb_key:
        b64  = base64.b64encode(buf.read()).decode("utf-8")
        resp = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": imgbb_key, "image": b64, "expiration": 604800},
        )
        if resp.ok:
            url = resp.json()["data"]["url"]
            return jsonify({"url": url, "status": "ok"})
        return jsonify({"error": "ImgBB upload falhou", "detail": resp.text}), 500

    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
