from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import io, os, requests, base64, threading

app = Flask(__name__)

# ── Font management ────────────────────────────────────────────────────────────
_FONT_CACHE = "/tmp/carousel_fonts"
os.makedirs(_FONT_CACHE, exist_ok=True)

FONT_URLS = {
    "playfair": "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "inter":    "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
}

_font_locks = {k: threading.Lock() for k in FONT_URLS}

def _font_path(name):
    path = os.path.join(_FONT_CACHE, f"{name}.ttf")
    with _font_locks[name]:
        if not os.path.exists(path):
            r = requests.get(FONT_URLS[name], timeout=30)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
    return path

def fnt(name, size, weight=400):
    try:
        path = _font_path(name)
        font = ImageFont.truetype(path, size)
        try:
            font.set_variation_by_axes({"wght": weight})
        except Exception:
            pass
        return font
    except Exception:
        return ImageFont.load_default()

# Pre-download fonts in background on startup
def _prefetch():
    for name in FONT_URLS:
        try:
            _font_path(name)
        except Exception:
            pass

threading.Thread(target=_prefetch, daemon=True).start()

# ── Theme ──────────────────────────────────────────────────────────────────────
def _theme(style):
    if style == "claro":
        return dict(
            BG=(245, 240, 232),          # #F5F0E8 bege
            ACCENT=(224, 92, 26),        # #E05C1A laranja terracota
            ACCENT_LIGHT=(245, 220, 205),# laranja muito claro para watermark
            TITLE_C=(26, 26, 26),        # quase preto
            BODY_C=(50, 48, 44),         # cinza escuro
            MUTED=(140, 128, 106),
            CARD_BG=(255, 253, 250),     # branco levemente quente
            TAG_BG=(224, 92, 26),
            TAG_FG=(255, 253, 250),
            DIVIDER=(224, 92, 26),
            FOOTER_C=(160, 148, 130),
            NUM_C=(235, 215, 200),       # número watermark
        )
    else:  # escuro
        return dict(
            BG=(9, 9, 26),
            ACCENT=(242, 185, 30),
            ACCENT_LIGHT=(50, 40, 10),
            TITLE_C=(238, 238, 248),
            BODY_C=(200, 200, 220),
            MUTED=(140, 140, 165),
            CARD_BG=(20, 20, 45),
            TAG_BG=(242, 185, 30),
            TAG_FG=(9, 9, 26),
            DIVIDER=(242, 185, 30),
            FOOTER_C=(90, 85, 110),
            NUM_C=(25, 25, 50),
        )

# ── Helpers ────────────────────────────────────────────────────────────────────
def parse_rich(text):
    """Split text into [(segment, is_bold), ...] based on **markers**."""
    parts = []
    bold = False
    buf = ""
    i = 0
    while i < len(text):
        if text[i:i+2] == "**":
            if buf:
                parts.append((buf, bold))
                buf = ""
            bold = not bold
            i += 2
        else:
            buf += text[i]
            i += 1
    if buf:
        parts.append((buf, bold))
    return parts

def draw_text_rich(draw, text, x, y, max_width, font_normal, font_bold, fill, line_spacing=16):
    """Word-wrap text with **bold** inline markers."""
    segments = parse_rich(text)
    # Flatten into tokens: (word, is_bold, has_trailing_space)
    tokens = []
    for seg, is_bold in segments:
        words = seg.split(" ")
        for j, w in enumerate(words):
            if w:
                tokens.append((w, is_bold))
            if j < len(words) - 1:
                tokens.append((" ", is_bold))

    # Build lines
    lines = []        # list of [(word, is_bold)]
    current = []
    current_w = 0
    for (word, is_bold) in tokens:
        f = font_bold if is_bold else font_normal
        wb = draw.textbbox((0, 0), word, font=f)
        ww = wb[2] - wb[0]
        if current_w + ww <= max_width:
            current.append((word, is_bold))
            current_w += ww
        else:
            if word.strip() == "":
                continue
            if current:
                lines.append(current)
            current = [(word, is_bold)]
            current_w = ww
    if current:
        lines.append(current)

    for line in lines:
        lx = x
        line_h = 0
        for (word, is_bold) in line:
            f = font_bold if is_bold else font_normal
            draw.text((lx, y), word, fill=fill, font=f)
            wb = draw.textbbox((0, 0), word, font=f)
            lx += wb[2] - wb[0]
            line_h = max(line_h, wb[3] - wb[1])
        y += line_h + line_spacing
    return y

def draw_text_wrapped(draw, text, x, y, max_width, font, fill, line_spacing=10):
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

def draw_rounded_rect(draw, xy, radius, fill):
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.ellipse([x0, y0, x0 + 2*radius, y0 + 2*radius], fill=fill)
    draw.ellipse([x1 - 2*radius, y0, x1, y0 + 2*radius], fill=fill)
    draw.ellipse([x0, y1 - 2*radius, x0 + 2*radius, y1], fill=fill)
    draw.ellipse([x1 - 2*radius, y1 - 2*radius, x1, y1], fill=fill)

# ── Layout: default (1 pergunta/ideia por slide) ───────────────────────────────
def generate_slide(title, body, slide_num, total_slides,
                   style="claro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1080
    t = _theme(style)

    img = Image.new("RGB", (W, H), t["BG"])
    draw = ImageDraw.Draw(img)

    PAD   = 72   # margem externa
    INNER = 108  # início do conteúdo

    # ── Barra lateral laranja (esquerda) ──────────────────────────────────────
    draw.rectangle([(PAD, PAD), (PAD + 7, H - PAD)], fill=t["ACCENT"])

    # ── Número watermark (grande, fundo) ──────────────────────────────────────
    f_wm = fnt("playfair", 420, 900)
    wm = str(slide_num)
    wb = draw.textbbox((0, 0), wm, font=f_wm)
    wm_x = W - PAD - (wb[2] - wb[0]) + 20
    wm_y = H - PAD - (wb[3] - wb[1]) + 40
    draw.text((wm_x, wm_y), wm, fill=t["NUM_C"], font=f_wm)

    y = PAD + 40

    # ── Macrotema (badge laranja arredondado) ─────────────────────────────────
    if macrotema:
        f_tag = fnt("inter", 24, 700)
        tb = draw.textbbox((0, 0), macrotema.upper(), font=f_tag)
        tag_w = tb[2] - tb[0] + 32
        tag_h = 36
        draw_rounded_rect(draw, (INNER, y, INNER + tag_w, y + tag_h), 8, t["TAG_BG"])
        draw.text((INNER + 16, y + 6), macrotema.upper(), fill=t["TAG_FG"], font=f_tag)
        y += tag_h + 24
    else:
        y += 10

    # ── Linha separadora topo ─────────────────────────────────────────────────
    draw.rectangle([(INNER, y), (W - PAD, y + 1)], fill=t["MUTED"])
    y += 20

    # ── Título ────────────────────────────────────────────────────────────────
    TEXT_W = W - INNER - PAD - 20
    f_title = fnt("playfair", 82, 800)
    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, t["TITLE_C"], line_spacing=10)
    y += 24

    # ── Divisor laranja curto ──────────────────────────────────────────────────
    draw.rectangle([(INNER, y), (INNER + 72, y + 5)], fill=t["ACCENT"])
    y += 40

    # ── Corpo ─────────────────────────────────────────────────────────────────
    if body:
        f_body      = fnt("inter", 40, 400)
        f_body_bold = fnt("inter", 40, 700)
        y = draw_text_rich(draw, body, INNER, y, TEXT_W, f_body, f_body_bold, t["BODY_C"], line_spacing=16)

    # ── Rodapé ────────────────────────────────────────────────────────────────
    footer_y = H - PAD - 50
    draw.rectangle([(INNER, footer_y), (W - PAD, footer_y + 1)], fill=t["ACCENT"])
    f_footer = fnt("inter", 26, 400)
    draw.text((INNER, footer_y + 12), handle, fill=t["FOOTER_C"], font=f_footer)

    return img

# ── Layout: lista ─────────────────────────────────────────────────────────────
def generate_slide_lista(title, items, slide_num, total_slides,
                          style="claro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1080
    t = _theme(style)
    img = Image.new("RGB", (W, H), t["BG"])
    draw = ImageDraw.Draw(img)

    PAD, INNER = 72, 108
    draw.rectangle([(PAD, PAD), (PAD + 7, H - PAD)], fill=t["ACCENT"])

    y = PAD + 40

    if macrotema:
        f_tag = fnt("inter", 24, 700)
        tb = draw.textbbox((0, 0), macrotema.upper(), font=f_tag)
        tag_w = tb[2] - tb[0] + 32
        draw_rounded_rect(draw, (INNER, y, INNER + tag_w, y + 36), 8, t["TAG_BG"])
        draw.text((INNER + 16, y + 6), macrotema.upper(), fill=t["TAG_FG"], font=f_tag)
        y += 60

    draw.rectangle([(INNER, y), (W - PAD, y + 1)], fill=t["MUTED"])
    y += 20

    TEXT_W = W - INNER - PAD - 20
    f_title = fnt("playfair", 62, 800)
    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, t["TITLE_C"], line_spacing=6)
    y += 16
    draw.rectangle([(INNER, y), (INNER + 72, y + 4)], fill=t["ACCENT"])
    y += 28

    f_num  = fnt("playfair", 30, 700)
    f_itit = fnt("inter", 32, 600)
    f_ibody= fnt("inter", 26, 400)

    for item in items:
        n_text  = item.get("num", "")
        i_title = item.get("title", "")
        i_body  = item.get("body", "")

        # Número em círculo laranja
        nb = draw.textbbox((0, 0), n_text, font=f_num)
        r = 22
        cx, cy = INNER + r, y + r
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=t["ACCENT"])
        draw.text((cx - (nb[2]-nb[0])//2, cy - (nb[3]-nb[1])//2 - 2), n_text, fill=t["TAG_FG"], font=f_num)

        ix = INNER + r*2 + 16
        iw = TEXT_W - r*2 - 16
        y_before = y
        y = draw_text_wrapped(draw, i_title, ix, y, iw, f_itit, t["BODY_C"], line_spacing=3)
        if i_body:
            y = draw_text_wrapped(draw, i_body, ix, y + 2, iw, f_ibody, t["MUTED"], line_spacing=3)
        y = max(y, y_before + r*2 + 10) + 18

    footer_y = H - PAD - 50
    draw.rectangle([(INNER, footer_y), (W - PAD, footer_y + 1)], fill=t["ACCENT"])
    f_footer = fnt("inter", 26, 400)
    draw.text((INNER, footer_y + 12), handle, fill=t["FOOTER_C"], font=f_footer)

    return img

# ── Layout: grid ──────────────────────────────────────────────────────────────
def generate_slide_grid(title, items, slide_num, total_slides,
                         style="claro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1080
    t = _theme(style)
    img = Image.new("RGB", (W, H), t["BG"])
    draw = ImageDraw.Draw(img)

    PAD, INNER = 72, 108
    draw.rectangle([(PAD, PAD), (PAD + 7, H - PAD)], fill=t["ACCENT"])

    y = PAD + 40
    if macrotema:
        f_tag = fnt("inter", 24, 700)
        tb = draw.textbbox((0, 0), macrotema.upper(), font=f_tag)
        tag_w = tb[2] - tb[0] + 32
        draw_rounded_rect(draw, (INNER, y, INNER + tag_w, y + 36), 8, t["TAG_BG"])
        draw.text((INNER + 16, y + 6), macrotema.upper(), fill=t["TAG_FG"], font=f_tag)
        y += 60

    draw.rectangle([(INNER, y), (W - PAD, y + 1)], fill=t["MUTED"])
    y += 20

    TEXT_W = W - INNER - PAD - 20
    f_title = fnt("playfair", 56, 800)
    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, t["TITLE_C"], line_spacing=4)
    y += 14
    draw.rectangle([(INNER, y), (INNER + 72, y + 4)], fill=t["ACCENT"])
    y += 28

    GAP    = 20
    CELL_W = (TEXT_W - GAP) // 2
    n_rows = max(1, (len(items) + 1) // 2)
    avail  = H - PAD - 60 - y
    CELL_H = min(190, max(110, (avail - (n_rows-1)*GAP) // n_rows))

    f_num_big = fnt("playfair", 44, 900)
    f_ctitle  = fnt("inter", 26, 600)
    f_cbody   = fnt("inter", 22, 400)

    for i, item in enumerate(items):
        col = i % 2
        row = i // 2
        cx  = INNER + col * (CELL_W + GAP)
        cy  = y + row * (CELL_H + GAP)

        draw_rounded_rect(draw, (cx, cy, cx + CELL_W, cy + CELL_H), 12, t["CARD_BG"])
        draw.rectangle([(cx, cy, cx + 6, cy + CELL_H)], fill=t["ACCENT"])

        n_text = item.get("num", f"{i+1:02d}")
        nb = draw.textbbox((0, 0), n_text, font=f_num_big)
        draw.text((cx + 14, cy + 8), n_text, fill=t["ACCENT_LIGHT"], font=f_num_big)

        ty = cy + 14 + (nb[3]-nb[1]) + 4
        ty = draw_text_wrapped(draw, item.get("title",""), cx+14, ty, CELL_W-28, f_ctitle, t["BODY_C"], 2)
        if item.get("body"):
            draw_text_wrapped(draw, item["body"], cx+14, ty+2, CELL_W-28, f_cbody, t["MUTED"], 2)

    footer_y = H - PAD - 50
    draw.rectangle([(INNER, footer_y), (W - PAD, footer_y + 1)], fill=t["ACCENT"])
    f_footer = fnt("inter", 26, 400)
    draw.text((INNER, footer_y + 12), handle, fill=t["FOOTER_C"], font=f_footer)

    return img

# ── Router ────────────────────────────────────────────────────────────────────
def parse_items(body_text):
    items, num = [], 1
    for line in body_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line:
            continue
        if "|" in line:
            parts = line.split("|", 1)
            items.append({"num": f"{num:02d}", "title": parts[0].strip(), "body": parts[1].strip()})
        else:
            items.append({"num": f"{num:02d}", "title": line, "body": ""})
        num += 1
    return items

def make_slide(layout, title, body, items, slide_num, total_slides, style, macrotema):
    if layout in ("lista", "grid"):
        if not items:
            items = parse_items(body)
        if items:
            fn = generate_slide_lista if layout == "lista" else generate_slide_grid
            return fn(title, items, slide_num, total_slides, style, macrotema)
    return generate_slide(title, body, slide_num, total_slides, style, macrotema)

# ── /generate ─────────────────────────────────────────────────────────────────
@app.route("/generate", methods=["POST"])
def generate():
    data       = request.get_json(force=True)
    title      = data.get("title", "")
    body       = data.get("body", "")
    slide_num  = int(data.get("slide_num", 1))
    total      = int(data.get("total_slides", 1))
    style      = data.get("style", "claro")
    macrotema  = data.get("macrotema", "")
    imgbb_key  = data.get("imgbb_key", "")
    layout     = data.get("layout", "default")
    items      = data.get("items", [])

    img = make_slide(layout, title, body, items, slide_num, total, style, macrotema)
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

# ── /health ───────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
