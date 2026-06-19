from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import io, os, requests, base64, threading, re

app = Flask(__name__)

# ── Font management ────────────────────────────────────────────────────────────
_FONT_CACHE = "/tmp/carousel_fonts"
os.makedirs(_FONT_CACHE, exist_ok=True)

FONT_URLS = {
    "playfair": "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "playfair_italic": "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay-Italic%5Bwght%5D.ttf",
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
    # Light theme matches the beige aesthetic of tenfoldmarc precisely
    if style == "claro":
        return dict(
            BG=(251, 249, 245),          # Off-white / Cream
            ACCENT=(186, 92, 58),        # Soft Terracota
            ACCENT_BG=(247, 235, 226),   # Very light Terracota for callout background
            TITLE_C=(45, 35, 30),        # Deep Charcoal Espresso
            BODY_C=(60, 50, 45),         # Espresso body text
            MUTED=(180, 170, 160),       # Muted Sand / Grey
            CARD_BG=(255, 255, 255),     # Off-white card
            DIVIDER=(235, 230, 225),     # Light grey divisor line
            BG_NUM=(244, 237, 230),      # Giant background watermark number
        )
    else:  # Dark theme counterpart
        return dict(
            BG=(15, 15, 25),             # Deep night blue
            ACCENT=(212, 175, 55),       # Gold
            ACCENT_BG=(35, 30, 15),      # Light gold-tinted dark background
            TITLE_C=(255, 255, 255),
            BODY_C=(210, 210, 220),
            MUTED=(110, 110, 130),
            CARD_BG=(22, 22, 40),
            DIVIDER=(35, 35, 55),
            BG_NUM=(22, 22, 32),
        )

# ── Helpers ────────────────────────────────────────────────────────────────────
def draw_rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill, outline=outline, width=width)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x0, y0, x0 + 2*radius, y0 + 2*radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x1 - 2*radius, y0, x1, y0 + 2*radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x0, y1 - 2*radius, x0 + 2*radius, y1], fill=fill, outline=outline, width=width)
    draw.ellipse([x1 - 2*radius, y1 - 2*radius, x1, y1], fill=fill, outline=outline, width=width)

def draw_corner_marks(draw, W, H, PAD, color):
    # Top-Left L
    draw.line([(PAD, PAD + 24), (PAD, PAD), (PAD + 24, PAD)], fill=color, width=2)
    # Top-Right L
    draw.line([(W - PAD - 24, PAD), (W - PAD, PAD), (W - PAD, PAD + 24)], fill=color, width=2)
    # Bottom-Left L
    draw.line([(PAD, H - PAD - 24), (PAD, H - PAD), (PAD + 24, H - PAD)], fill=color, width=2)
    # Bottom-Right L
    draw.line([(W - PAD - 24, H - PAD), (W - PAD, H - PAD), (W - PAD, H - PAD - 24)], fill=color, width=2)

def parse_rich_text(text):
    # Splits text into parts detecting inline code blocks [like this] and bold **like this**
    pattern = re.compile(r"(\[.*?\]|\*\*.*?\*\*)")
    parts = []
    last_idx = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if start > last_idx:
            parts.append((text[last_idx:start], "normal"))
        token = match.group(0)
        if token.startswith("[") and token.endswith("]"):
            parts.append((token[1:-1], "code"))
        elif token.startswith("**") and token.endswith("**"):
            parts.append((token[2:-2], "bold"))
        last_idx = end
    if last_idx < len(text):
        parts.append((text[last_idx:], "normal"))
    return parts

def draw_rich_line(draw, x, y, parts, font_norm, font_bold, fill_color, accent_color, accent_bg_color):
    cx = x
    for text, style in parts:
        if style == "bold":
            draw.text((cx, y), text, fill=fill_color, font=font_bold)
            bbox = draw.textbbox((0, 0), text, font=font_bold)
            cx += bbox[2] - bbox[0]
        elif style == "code":
            # Draw a subtle background badge for code blocks
            bbox = draw.textbbox((0, 0), text, font=font_norm)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            draw_rounded_rect(draw, (cx - 4, y - 2, cx + w + 4, y + h + 6), 4, accent_bg_color)
            draw.text((cx, y), text, fill=accent_color, font=font_norm)
            cx += w + 8
        else:
            draw.text((cx, y), text, fill=fill_color, font=font_norm)
            bbox = draw.textbbox((0, 0), text, font=font_norm)
            cx += bbox[2] - bbox[0]

def wrap_rich_text(draw, text, max_width, font_norm, font_bold):
    words = text.split(" ")
    lines = []
    current_line = []
    current_w = 0
    
    for word in words:
        if not word:
            continue
        # Test word size (with bold font to be conservative)
        wb = draw.textbbox((0, 0), word + " ", font=font_bold)
        ww = wb[2] - wb[0]
        
        if current_w + ww <= max_width:
            current_line.append(word)
            current_w += ww
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_w = ww
            
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def draw_rich_paragraph(draw, paragraph, x, y, max_width, font_norm, font_bold, fill_color, accent_color, accent_bg_color, line_spacing=12):
    lines = wrap_rich_text(draw, paragraph, max_width, font_norm, font_bold)
    for line in lines:
        parts = parse_rich_text(line)
        draw_rich_line(draw, x, y, parts, font_norm, font_bold, fill_color, accent_color, accent_bg_color)
        bbox = draw.textbbox((0, 0), "Ap", font=font_bold)
        y += (bbox[3] - bbox[1]) + line_spacing
    return y

# ── Title Rich Rendering ───────────────────────────────────────────────────────
def parse_title_rich(text):
    # Splits by asterisks to find words that should be Terracota and Italic
    pattern = re.compile(r"(\*[^*]+\*)")
    parts = []
    last_idx = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if start > last_idx:
            parts.append((text[last_idx:start], False))
        token = match.group(0)
        parts.append((token[1:-1], True))
        last_idx = end
    if last_idx < len(text):
        parts.append((text[last_idx:], False))
    return parts

def draw_title_rich(draw, text, x, y, max_width, font_reg, font_italic, title_color, accent_color, line_spacing=12):
    # Wrap text conservatively using regular title font
    words = text.split(" ")
    lines = []
    current_line = []
    current_w = 0
    
    for word in words:
        if not word:
            continue
        clean_word = word.replace("*", "")
        wb = draw.textbbox((0, 0), clean_word + " ", font=font_reg)
        ww = wb[2] - wb[0]
        
        if current_w + ww <= max_width:
            current_line.append(word)
            current_w += ww
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_w = ww
            
    if current_line:
        lines.append(" ".join(current_line))
        
    # Render line by line
    for line in lines:
        parts = parse_title_rich(line)
        cx = x
        line_h = 0
        for segment, is_accent in parts:
            f = font_italic if is_accent else font_reg
            c = accent_color if is_accent else title_color
            draw.text((cx, y), segment, fill=c, font=f)
            bbox = draw.textbbox((0, 0), segment, font=f)
            cx += bbox[2] - bbox[0]
            line_h = max(line_h, bbox[3] - bbox[1])
        y += line_h + line_spacing
        
    return y

# ── Layout: Default Slide (Serif Title, Bullet points, Callout box) ───────────
def generate_slide(title, body, slide_num, total_slides,
                   style="claro", macrotema="", handle="Igor Ladeira"):
    # 4:5 Portrait Ratio (1080 x 1350 px)
    W, H = 1080, 1350
    t = _theme(style)

    img = Image.new("RGB", (W, H), t["BG"])
    draw = ImageDraw.Draw(img)

    PAD   = 60
    INNER = 96
    TEXT_W = W - 2 * INNER

    # 1. Draw thin crop/corner marks in Terracota
    draw_corner_marks(draw, W, H, PAD, t["ACCENT"])

    # 2. Draw Header
    f_header = fnt("inter", 20, 700)
    # Left: Muted handler
    draw.text((INNER, PAD + 30), f"@{handle.replace(' ', '').upper()}", fill=t["MUTED"], font=f_header)
    # Right: Slide position (03 / 11)
    slide_text = f"{slide_num:02d}/{total_slides:02d}"
    draw.text((W - INNER - 50, PAD + 30), slide_text, fill=t["MUTED"], font=f_header)

    y = PAD + 80

    # 3. Draw step indicator (STEP 02 / PASSO 02)
    f_step = fnt("inter", 22, 700)
    step_str = f"PASSO {slide_num:02d}"
    draw.text((INNER, y), step_str, fill=t["ACCENT"], font=f_step)

    # 4. Draw Giant background watermark number
    f_bgnum = fnt("playfair_italic", 440, 900)
    bgnum_str = f"{slide_num:02d}"
    nb = draw.textbbox((0, 0), bgnum_str, font=f_bgnum)
    draw.text((W - INNER - (nb[2]-nb[0]), y - 30), bgnum_str, fill=t["BG_NUM"], font=f_bgnum)

    y += 40

    # 5. Draw Rich Title (with Italic words support)
    f_title_reg = fnt("playfair", 84, 800)
    f_title_ital = fnt("playfair_italic", 84, 800)
    y = draw_title_rich(draw, title, INNER, y, TEXT_W, f_title_reg, f_title_ital, t["TITLE_C"], t["ACCENT"], line_spacing=12)
    y += 18

    # Title underline
    draw.line([(INNER, y), (INNER + 80, y)], fill=t["ACCENT"], width=4)
    y += 40

    # 6. Parse Body content
    # Extract callout lines (starting with > or final quote blocks)
    lines = body.strip().split("\n")
    body_lines = []
    callout_text = ""
    
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        if line_s.startswith(">"):
            callout_text = line_s[1:].strip()
        else:
            body_lines.append(line)

    f_body = fnt("inter", 32, 400)
    f_body_bold = fnt("inter", 32, 700)

    # 7. Draw Bullet points or paragraphs
    for line in body_lines:
        line_s = line.strip()
        is_bullet = line_s.startswith("-")
        clean_text = line_s[1:].strip() if is_bullet else line_s
        
        if is_bullet:
            # Draw elegant bullet circle
            bullet_y = y + 16
            draw.ellipse([(INNER + 4, bullet_y - 6), (INNER + 16, bullet_y + 6)], fill=t["ACCENT"])
            y = draw_rich_paragraph(draw, clean_text, INNER + 32, y, TEXT_W - 32, f_body, f_body_bold, t["BODY_C"], t["ACCENT"], t["ACCENT_BG"], line_spacing=10)
        else:
            y = draw_rich_paragraph(draw, clean_text, INNER, y, TEXT_W, f_body, f_body_bold, t["BODY_C"], t["ACCENT"], t["ACCENT_BG"], line_spacing=10)
        y += 16

    # 8. Draw Callout Box at the bottom if present
    if callout_text:
        callout_y = H - PAD - 260
        callout_h = 160
        # Draw soft background
        draw_rounded_rect(draw, (INNER, callout_y, W - INNER, callout_y + callout_h), 8, t["ACCENT_BG"])
        # Draw thick left accent line
        draw.rectangle([(INNER, callout_y + 12), (INNER + 6, callout_y + callout_h - 12)], fill=t["ACCENT"])
        
        # Render callout text inside
        f_callout = fnt("inter", 28, 500)
        f_callout_bold = fnt("inter", 28, 700)
        draw_rich_paragraph(draw, callout_text, INNER + 28, callout_y + 24, TEXT_W - 48, f_callout, f_callout_bold, t["TITLE_C"], t["ACCENT"], t["ACCENT_BG"], line_spacing=6)

    # 9. Draw Footer
    footer_y = H - PAD - 40
    draw.line([(INNER, footer_y), (W - INNER, footer_y)], fill=t["DIVIDER"], width=1)
    
    f_footer = fnt("inter", 18, 600)
    draw.text((INNER, footer_y + 12), f"{handle.upper()}  ·  GESTAO PATRIMONIAL", fill=t["MUTED"], font=f_footer)
    draw.text((W - INNER - 90, footer_y + 12), "DESLIZE  ->", fill=t["ACCENT"], font=f_footer)

    return img

# ── Layout: List / Cards Slide (Grid of 2x2 cards if 4 items) ──────────────────
def generate_slide_lista(title, items, slide_num, total_slides,
                          style="claro", macrotema="", handle="Igor Ladeira"):
    # If exactly 4 items, let's draw the 2x2 grid card layout shown in tenfoldmarc screenshot 1
    if len(items) == 4:
        return generate_slide_grid(title, items, slide_num, total_slides, style, macrotema, handle)
        
    return generate_slide(title, "\n".join([f"- **{it['title']}** {it['body']}" for it in items]), slide_num, total_slides, style, macrotema, handle)

def generate_slide_grid(title, items, slide_num, total_slides,
                         style="claro", macrotema="", handle="Igor Ladeira"):
    W, H = 1080, 1350
    t = _theme(style)
    
    img = Image.new("RGB", (W, H), t["BG"])
    draw = ImageDraw.Draw(img)

    PAD   = 60
    INNER = 96
    TEXT_W = W - 2 * INNER

    draw_corner_marks(draw, W, H, PAD, t["ACCENT"])

    f_header = fnt("inter", 20, 700)
    draw.text((INNER, PAD + 30), f"@{handle.replace(' ', '').upper()}", fill=t["MUTED"], font=f_header)
    slide_text = f"{slide_num:02d}/{total_slides:02d}"
    draw.text((W - INNER - 50, PAD + 30), slide_text, fill=t["MUTED"], font=f_header)

    y = PAD + 80
    f_step = fnt("inter", 22, 700)
    draw.text((INNER, y), f"PASSO {slide_num:02d}", fill=t["ACCENT"], font=f_step)

    # Giant watermark background number
    f_bgnum = fnt("playfair_italic", 440, 900)
    bgnum_str = f"{slide_num:02d}"
    nb = draw.textbbox((0, 0), bgnum_str, font=f_bgnum)
    draw.text((W - INNER - (nb[2]-nb[0]), y - 30), bgnum_str, fill=t["BG_NUM"], font=f_bgnum)

    y += 40
    f_title_reg = fnt("playfair", 84, 800)
    f_title_ital = fnt("playfair_italic", 84, 800)
    y = draw_title_rich(draw, title, INNER, y, TEXT_W, f_title_reg, f_title_ital, t["TITLE_C"], t["ACCENT"], line_spacing=12)
    y += 18
    draw.line([(INNER, y), (INNER + 80, y)], fill=t["ACCENT"], width=4)
    y += 50

    # Draw 2x2 Grid Cards
    GAP = 28
    CARD_W = (TEXT_W - GAP) // 2
    CARD_H = 260

    f_num_big = fnt("playfair_italic", 42, 800)
    f_ctitle  = fnt("inter", 30, 700)
    f_cbody   = fnt("inter", 24, 400)
    f_tag = fnt("inter", 16, 700)

    for i, item in enumerate(items[:4]):
        col = i % 2
        row = i // 2
        cx  = INNER + col * (CARD_W + GAP)
        cy  = y + row * (CARD_H + GAP)

        # Draw Clean White Rounded Card
        draw_rounded_rect(draw, (cx, cy, cx + CARD_W, cy + CARD_H), 12, t["CARD_BG"], outline=t["DIVIDER"], width=1)
        
        # Top margin indicator category inside card
        n_text = item.get("num", f"ITEM {i+1:02d}")
        draw.text((cx + 20, cy + 18), n_text.upper(), fill=t["MUTED"], font=f_tag)

        # Item Title next to a small accent line
        ty = cy + 44
        draw.rectangle([(cx + 20, ty + 6), (cx + 20 + 12, ty + 10)], fill=t["ACCENT"])
        draw.text((cx + 40, ty), item.get("title", ""), fill=t["TITLE_C"], font=f_ctitle)
        
        # Item body description inside card
        body_y = ty + 42
        draw_text_wrapped(draw, item.get("body", ""), cx + 20, body_y, CARD_W - 40, f_cbody, t["BODY_C"], line_spacing=4)

    # Footer
    footer_y = H - PAD - 40
    draw.line([(INNER, footer_y), (W - INNER, footer_y)], fill=t["DIVIDER"], width=1)
    f_footer = fnt("inter", 18, 600)
    draw.text((INNER, footer_y + 12), f"{handle.upper()}  ·  GESTAO PATRIMONIAL", fill=t["MUTED"], font=f_footer)
    draw.text((W - INNER - 90, footer_y + 12), "DESLIZE  ->", fill=t["ACCENT"], font=f_footer)

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
            items.append({"num": f"PASSO {num:02d}", "title": parts[0].strip(), "body": parts[1].strip()})
        else:
            items.append({"num": f"PASSO {num:02d}", "title": line, "body": ""})
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
