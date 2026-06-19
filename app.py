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
            BG_START=(249, 246, 240),    # Creme muito claro
            BG_END=(242, 235, 224),      # Bege quente suave
            ACCENT=(165, 75, 36),        # Terracota elegante
            ACCENT_LIGHT=(235, 215, 200),# Terracota pastel
            TITLE_C=(45, 25, 16),        # Espresso profundo
            BODY_C=(60, 40, 30),         # Espresso suave
            MUTED=(180, 160, 145),       # Areia suave
            CARD_BG=(252, 250, 246),     # Off-white limpo
            TAG_BG=(165, 75, 36),
            TAG_FG=(252, 250, 246),
            DIVIDER=(220, 210, 195),
            FOOTER_C=(150, 130, 115),
        )
    else:  # escuro
        return dict(
            BG_START=(14, 14, 38),       # Azul noite profundo
            BG_END=(5, 5, 20),           # Escuro quase preto
            ACCENT=(212, 175, 55),       # Dourado rico
            ACCENT_LIGHT=(55, 45, 20),   # Dourado muito escuro
            TITLE_C=(255, 255, 255),
            BODY_C=(220, 220, 230),
            MUTED=(120, 120, 145),
            CARD_BG=(22, 22, 56),
            TAG_BG=(212, 175, 55),
            TAG_FG=(5, 5, 20),
            DIVIDER=(40, 40, 75),
            FOOTER_C=(96, 96, 128),
        )

# ── Helpers ────────────────────────────────────────────────────────────────────
def draw_gradient(draw, W, H, c1, c2):
    for y in range(H):
        t = y / H
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

def draw_diamond(draw, cx, cy, r, fill):
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)

def parse_rich(text):
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
    segments = parse_rich(text)
    tokens = []
    for seg, is_bold in segments:
        words = seg.split(" ")
        for j, w in enumerate(words):
            if w:
                tokens.append((w, is_bold))
            if j < len(words) - 1:
                tokens.append((" ", is_bold))

    lines = []
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

def draw_rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill, outline=outline, width=width)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x0, y0, x0 + 2*radius, y0 + 2*radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x1 - 2*radius, y0, x1, y0 + 2*radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x0, y1 - 2*radius, x0 + 2*radius, y1], fill=fill, outline=outline, width=width)
    draw.ellipse([x1 - 2*radius, y1 - 2*radius, x1, y1], fill=fill, outline=outline, width=width)

# ── Layout: default ────────────────────────────────────────────────────────────
def generate_slide(title, body, slide_num, total_slides,
                   style="claro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1080
    t = _theme(style)

    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, W, H, t["BG_START"], t["BG_END"])

    PAD   = 72
    INNER = 108

    # Linha vertical esquerda sutil (1px)
    draw.line([(PAD, PAD + 40), (PAD, H - PAD - 60)], fill=t["MUTED"], width=1)

    # Marcador elegante de slide (SLIDE 01 / 05)
    f_slide = fnt("inter", 20, 600)
    slide_text = f"{slide_num:02d} / {total_slides:02d}"
    draw.text((W - PAD - 80, PAD + 44), slide_text, fill=t["MUTED"], font=f_slide)

    y = PAD + 40

    # Badge macrotema
    if macrotema:
        f_tag = fnt("inter", 22, 700)
        tb = draw.textbbox((0, 0), macrotema.upper(), font=f_tag)
        tag_w = tb[2] - tb[0] + 32
        tag_h = 34
        draw_rounded_rect(draw, (INNER, y, INNER + tag_w, y + tag_h), 6, t["TAG_BG"])
        draw.text((INNER + 16, y + 5), macrotema.upper(), fill=t["TAG_FG"], font=f_tag)
        
        # Desenha pequeno diamante decorativo no canto oposto
        draw_diamond(draw, W - PAD - 120, y + 17, 6, t["ACCENT"])
        y += tag_h + 30
    else:
        y += 10

    # Divisor horizontal sutil
    draw.line([(INNER, y), (W - PAD, y)], fill=t["DIVIDER"], width=1)
    y += 30

    TEXT_W = W - INNER - PAD - 20
    
    # Título Serif Premium
    f_title = fnt("playfair", 72, 800)
    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, t["TITLE_C"], line_spacing=12)
    y += 24

    # Linha sutil abaixo do título
    draw.line([(INNER, y), (INNER + 60, y)], fill=t["ACCENT"], width=3)
    y += 36

    if body:
        f_body      = fnt("inter", 36, 400)
        f_body_bold = fnt("inter", 36, 700)
        y = draw_text_rich(draw, body, INNER, y, TEXT_W, f_body, f_body_bold, t["BODY_C"], line_spacing=18)

    # Footer
    footer_y = H - PAD - 50
    draw.line([(PAD, footer_y), (W - PAD, footer_y)], fill=t["MUTED"], width=1)
    
    f_footer = fnt("inter", 20, 600)
    draw.text((INNER, footer_y + 16), "GESTAO PATRIMONIAL EXCLUSIVA | WEALTH MANAGEMENT", fill=t["FOOTER_C"], font=f_footer)
    
    ig_handle = "@igorladeira85"
    hb_ig = draw.textbbox((0, 0), ig_handle, font=f_footer)
    ig_w = hb_ig[2] - hb_ig[0]
    draw.text((W - PAD - ig_w, footer_y + 16), ig_handle, fill=t["FOOTER_C"], font=f_footer)

    return img

# ── Layout: lista ─────────────────────────────────────────────────────────────
def generate_slide_lista(title, items, slide_num, total_slides,
                          style="claro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1080
    t = _theme(style)
    
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, W, H, t["BG_START"], t["BG_END"])

    PAD, INNER = 72, 108
    draw.line([(PAD, PAD + 40), (PAD, H - PAD - 60)], fill=t["MUTED"], width=1)

    f_slide = fnt("inter", 20, 600)
    slide_text = f"{slide_num:02d} / {total_slides:02d}"
    draw.text((W - PAD - 80, PAD + 44), slide_text, fill=t["MUTED"], font=f_slide)

    y = PAD + 40
    if macrotema:
        f_tag = fnt("inter", 22, 700)
        tb = draw.textbbox((0, 0), macrotema.upper(), font=f_tag)
        tag_w = tb[2] - tb[0] + 32
        tag_h = 34
        draw_rounded_rect(draw, (INNER, y, INNER + tag_w, y + tag_h), 6, t["TAG_BG"])
        draw.text((INNER + 16, y + 5), macrotema.upper(), fill=t["TAG_FG"], font=f_tag)
        draw_diamond(draw, W - PAD - 120, y + 17, 6, t["ACCENT"])
        y += tag_h + 30

    draw.line([(INNER, y), (W - PAD, y)], fill=t["DIVIDER"], width=1)
    y += 30

    TEXT_W = W - INNER - PAD - 20
    f_title = fnt("playfair", 60, 800)
    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, t["TITLE_C"], line_spacing=8)
    y += 16
    draw.line([(INNER, y), (INNER + 60, y)], fill=t["ACCENT"], width=3)
    y += 36

    f_itit = fnt("inter", 32, 600)
    f_ibody= fnt("inter", 26, 400)

    for item in items:
        # Elegant diamond bullet point instead of numbered badge
        bullet_x = INNER + 8
        bullet_y = y + 16
        draw_diamond(draw, bullet_x, bullet_y, 6, t["ACCENT"])

        ix = INNER + 32
        iw = TEXT_W - 32
        y_before = y
        y = draw_text_wrapped(draw, item.get("title", ""), ix, y, iw, f_itit, t["BODY_C"], line_spacing=4)
        if item.get("body"):
            y = draw_text_wrapped(draw, item["body"], ix, y + 4, iw, f_ibody, t["MUTED"], line_spacing=4)
        y = max(y, y_before + 32) + 24

    # Footer
    footer_y = H - PAD - 50
    draw.line([(PAD, footer_y), (W - PAD, footer_y)], fill=t["MUTED"], width=1)
    f_footer = fnt("inter", 20, 600)
    draw.text((INNER, footer_y + 16), "GESTAO PATRIMONIAL EXCLUSIVA | WEALTH MANAGEMENT", fill=t["FOOTER_C"], font=f_footer)
    
    ig_handle = "@igorladeira85"
    hb_ig = draw.textbbox((0, 0), ig_handle, font=f_footer)
    ig_w = hb_ig[2] - hb_ig[0]
    draw.text((W - PAD - ig_w, footer_y + 16), ig_handle, fill=t["FOOTER_C"], font=f_footer)

    return img

# ── Layout: grid ──────────────────────────────────────────────────────────────
def generate_slide_grid(title, items, slide_num, total_slides,
                         style="claro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1080
    t = _theme(style)
    
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, W, H, t["BG_START"], t["BG_END"])

    PAD, INNER = 72, 108
    draw.line([(PAD, PAD + 40), (PAD, H - PAD - 60)], fill=t["MUTED"], width=1)

    f_slide = fnt("inter", 20, 600)
    slide_text = f"{slide_num:02d} / {total_slides:02d}"
    draw.text((W - PAD - 80, PAD + 44), slide_text, fill=t["MUTED"], font=f_slide)

    y = PAD + 40
    if macrotema:
        f_tag = fnt("inter", 22, 700)
        tb = draw.textbbox((0, 0), macrotema.upper(), font=f_tag)
        tag_w = tb[2] - tb[0] + 32
        tag_h = 34
        draw_rounded_rect(draw, (INNER, y, INNER + tag_w, y + tag_h), 6, t["TAG_BG"])
        draw.text((INNER + 16, y + 5), macrotema.upper(), fill=t["TAG_FG"], font=f_tag)
        draw_diamond(draw, W - PAD - 120, y + 17, 6, t["ACCENT"])
        y += tag_h + 30

    draw.line([(INNER, y), (W - PAD, y)], fill=t["DIVIDER"], width=1)
    y += 30

    TEXT_W = W - INNER - PAD - 20
    f_title = fnt("playfair", 56, 800)
    y = draw_text_wrapped(draw, title, INNER, y, TEXT_W, f_title, t["TITLE_C"], line_spacing=6)
    y += 14
    draw.line([(INNER, y), (INNER + 60, y)], fill=t["ACCENT"], width=3)
    y += 36

    GAP    = 24
    CELL_W = (TEXT_W - GAP) // 2
    n_rows = max(1, (len(items) + 1) // 2)
    avail  = H - PAD - 60 - y
    CELL_H = min(190, max(110, (avail - (n_rows-1)*GAP) // n_rows))

    f_num_big = fnt("playfair", 38, 900)
    f_ctitle  = fnt("inter", 26, 600)
    f_cbody   = fnt("inter", 22, 400)

    for i, item in enumerate(items):
        col = i % 2
        row = i // 2
        cx  = INNER + col * (CELL_W + GAP)
        cy  = y + row * (CELL_H + GAP)

        # Elegant card with 1px border and very clean accent bar
        draw_rounded_rect(draw, (cx, cy, cx + CELL_W, cy + CELL_H), 8, t["CARD_BG"], outline=t["DIVIDER"], width=1)
        draw.rectangle([(cx, cy + 8), (cx + 4, cy + CELL_H - 8)], fill=t["ACCENT"])

        n_text = item.get("num", f"{i+1:02d}")
        draw.text((cx + 16, cy + 10), n_text, fill=t["ACCENT"], font=f_num_big)

        ty = cy + 10
        # Offset to prevent overlap with big number
        ty = draw_text_wrapped(draw, item.get("title", ""), cx + 54, ty, CELL_W - 68, f_ctitle, t["BODY_C"], 2)
        if item.get("body"):
            draw_text_wrapped(draw, item["body"], cx + 54, ty + 2, CELL_W - 68, f_cbody, t["MUTED"], 2)

    # Footer
    footer_y = H - PAD - 50
    draw.line([(PAD, footer_y), (W - PAD, footer_y)], fill=t["MUTED"], width=1)
    f_footer = fnt("inter", 20, 600)
    draw.text((INNER, footer_y + 16), "GESTAO PATRIMONIAL EXCLUSIVA | WEALTH MANAGEMENT", fill=t["FOOTER_C"], font=f_footer)
    
    ig_handle = "@igorladeira85"
    hb_ig = draw.textbbox((0, 0), ig_handle, font=f_footer)
    ig_w = hb_ig[2] - hb_ig[0]
    draw.text((W - PAD - ig_w, footer_y + 16), ig_handle, fill=t["FOOTER_C"], font=f_footer)

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
