"""Render a branded VITRINE share card (PNG) for an event and cache it in MinIO."""
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from core.http_safety import is_public_http_url
from core.media.storage import ensure_bucket, get_object, object_exists, public_url, put_image

logger = logging.getLogger(__name__)

W, H = 1080, 1350
INK = (11, 11, 11)
PLASTER = (244, 244, 239)
ACID = (204, 255, 0)
INK_DIM = (110, 110, 102)
CINNABAR = (230, 51, 18)

FONT_PATH = str(Path(__file__).resolve().parents[4] / "assets" / "fonts" / "Unbounded.ttf")

CAT_LABEL = {
    "concert": "Концерт",
    "theatre": "Театр",
    "exhibition": "Выставка",
    "cinema": "Кино",
    "standup": "Стендап",
    "festival": "Фестиваль",
    "lecture": "Лекция",
    "tour": "Экскурсия",
    "party": "Вечеринка",
    "quest": "Квест",
    "kids": "Детям",
    "other": "Событие",
}


def _font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT_PATH, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


# The VITRINE type stack: Unbounded (display/wordmark, above) + Golos Text (titles/prose — a neutral
# editorial grotesk with full CYRILLIC, unlike the app's Latin-only Familjen) + Martian Mono (codes/
# data). Bundled so the reminder card reads like the app's EventListRow instead of everything-in-
# Unbounded (which looked toy-like in a DM).
_FONTS_DIR = Path(__file__).resolve().parents[4] / "assets" / "fonts"
GROTESK_PATH = str(_FONTS_DIR / "GolosText.ttf")
MONO_PATH = str(_FONTS_DIR / "MartianMono.ttf")


def _grotesk(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(GROTESK_PATH, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def _mono(size: int, weight: int = 400, width: int = 100) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(MONO_PATH, size)
    try:
        f.set_variation_by_axes([weight, width])  # axes order: Weight, Width
    except Exception:
        pass
    return f


def _bolt(d: ImageDraw.ImageDraw, x: float, y: float, h: float, color) -> None:
    """A small lightning bolt — the 'starting soon' urgency mark. Height h, top-left at (x, y)."""
    w = h * 0.62
    pts = [(0.60, 0.0), (0.04, 0.58), (0.42, 0.58), (0.30, 1.0), (0.98, 0.40), (0.58, 0.40), (0.80, 0.0)]
    d.polygon([(x + px * w, y + py * h) for px, py in pts], fill=color)


def _pin_sm(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color=ACID) -> None:
    """A small map-pin glyph (acid by default, ink hole) for dark chips. Bulb centred near (cx, cy)."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    d.polygon([(cx - r * 0.62, cy + r * 0.35), (cx + r * 0.62, cy + r * 0.35), (cx, cy + r * 1.9)], fill=color)
    hr = r * 0.42
    d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=INK)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # Ellipsize whenever any text was dropped (later words cut to fit max_lines) — not only when
    # the last line itself overflows; shorten the last line so "…" fits.
    if lines and len("".join(lines).replace(" ", "")) < len(text.replace(" ", "")):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _pin(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=INK)
    d.polygon([(cx - r * 0.55, cy + r * 0.5), (cx + r * 0.55, cy + r * 0.5), (cx, cy + r * 1.95)], fill=INK)
    hr = r * 0.46
    d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=ACID)
    dr = r * 0.17
    d.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill=INK)


def render_card(title: str, meta: str, category: str, photo: bytes | None) -> bytes:
    img = Image.new("RGB", (W, H), PLASTER)
    d = ImageDraw.Draw(img)

    # Photo window (cover-fit) or an acid block when there's no image.
    px0, py0, px1, py1 = 20, 20, W - 20, 800
    if photo:
        try:
            ph = Image.open(io.BytesIO(photo)).convert("RGB")
            ph = ImageOps.fit(ph, (px1 - px0, py1 - py0), Image.LANCZOS)
            img.paste(ph, (px0, py0))
        except Exception:
            d.rectangle([px0, py0, px1, py1], fill=ACID)
    else:
        d.rectangle([px0, py0, px1, py1], fill=ACID)

    # Acid category tag over the photo's bottom-left.
    label = (CAT_LABEL.get(category, "Событие")).upper()
    cf = _font(30, 700)
    tw = d.textlength(label, font=cf)
    d.rectangle([px0 + 22, py1 - 60, px0 + 22 + tw + 36, py1 - 8], fill=ACID)
    d.text((px0 + 22 + 18, py1 - 54), label, font=cf, fill=INK)

    # Outer hairline frame + photo divider.
    d.rectangle([20, 20, W - 21, H - 21], outline=INK, width=3)
    d.line([px0, py1, px1, py1], fill=INK, width=3)

    # Cinnabar registration tick (signature).
    d.line([W - 70, 44, W - 44, 44], fill=CINNABAR, width=4)
    d.line([W - 44, 44, W - 44, 70], fill=CINNABAR, width=4)

    # Title.
    tf = _font(58, 800)
    x = 48
    y = 850
    for line in _wrap(d, title, tf, W - 96, 3):
        d.text((x, y), line, font=tf, fill=INK)
        y += 74

    # Meta (when · venue), single ellipsized line.
    mf = _font(28, 500)
    m = meta.upper()
    while m and d.textlength(m + "…", font=mf) > W - 96:
        m = m[:-1]
    if m and m != meta.upper():
        m = m.rstrip() + "…"
    d.text((x, y + 10), m, font=mf, fill=INK_DIM)

    # Wordmark lockup at the bottom: pin + окрест + tagline.
    by = H - 86
    _pin(d, 60, by - 6, 22)
    wf = _font(40, 800)
    d.text((92, by - 30), "окрест", font=wf, fill=INK)
    tagf = _font(22, 600)
    tag = "СОБЫТИЯ РЯДОМ"
    d.text((W - 48 - d.textlength(tag, font=tagf), by - 18), tag, font=tagf, fill=INK_DIM)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


# --- reminder CARD: a fully-composed VITRINE notification card ------------------------
# render_reminder_cover (above) stamped brand chrome on a bare 16:9 photo and left the when /
# title / venue / price to the Telegram caption — a thin photo over a wall of text. This bakes the
# WHOLE card (Unbounded wordmark · Familjen Grotesk title · Martian Mono data) into one frame, like
# the app's EventListRow, so the DM looks designed. The `when` is live, so it's rendered per send
# (cheap — reminders are low-volume) and streamed to Telegram as bytes, not a cached URL.
def render_reminder_card(item: dict, photo: bytes | None) -> bytes:
    W = 1080
    P = 46            # body padding
    PH = 700          # photo block height
    RULE = 6          # acid rule under the photo
    INK_LINE = (38, 38, 36)
    WHITE = (243, 243, 238)

    # photo block — kept BRIGHT (only a bottom scrim for the wordmark), the opposite of the old
    # darken-to-mud cover; cover-fit, acid fallback when there's no usable image.
    try:
        block = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (W, PH), Image.LANCZOS) if photo \
            else Image.new("RGB", (W, PH), ACID)
    except Exception:
        block = Image.new("RGB", (W, PH), ACID)
    pd = ImageDraw.Draw(block, "RGBA")
    gh = int(PH * 0.42)
    for i in range(gh):
        pd.line([(0, PH - gh + i), (W, PH - gh + i)], fill=(11, 11, 11, int(210 * (i / gh) ** 1.7)))
    wf = _font(46, 800)  # окрест wordmark, bottom-left, acid + underline
    pd.text((P, PH - 92), "окрест", font=wf, fill=ACID)
    ww = pd.textlength("окрест", font=wf)
    pd.rectangle([P, PH - 34, P + ww, PH - 28], fill=ACID)
    code = (item.get("code") or "").strip()
    if code:  # accession code, top-left ink tab (mono acid)
        cf = _mono(27, 600)
        cw = pd.textlength(code, font=cf); pad = 12
        pd.rectangle([28, 28, 28 + cw + 2 * pad, 78], fill=(11, 11, 11, 220))
        pd.text((40, 39), code, font=cf, fill=ACID)
    pd.line([W - 70, 40, W - 40, 40], fill=CINNABAR, width=5)  # cinnabar registration tick (signature)
    pd.line([W - 40, 40, W - 40, 70], fill=CINNABAR, width=5)

    # measure body so the canvas fits the content
    scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title = str(item.get("title") or "Событие").strip()
    tf = _grotesk(62, 700)
    tlines = _wrap(scratch, title, tf, W - 2 * P, 3)
    LH = 72
    body_top = PH + RULE
    urg_y = body_top + 40
    title_y = urg_y + 34 + 30
    meta_y = title_y + len(tlines) * LH + 16
    chip_y = meta_y + 30 + 34
    chip_h = 78
    H = chip_y + chip_h + P

    img = Image.new("RGB", (W, H), INK)
    img.paste(block, (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, PH, W, PH + RULE], fill=ACID)

    when = str(item.get("when") or "").strip()
    if when:  # urgency: bolt + when (mono acid)
        _bolt(d, P, urg_y, 38, ACID)
        d.text((P + 42, urg_y + 3), when, font=_mono(28, 500), fill=ACID)

    ty = title_y  # title (grotesk bold, white)
    for ln in tlines:
        d.text((P, ty), ln, font=tf, fill=WHITE)
        ty += LH

    cat = CAT_LABEL.get(item.get("category") or "", "Событие").upper()  # code · category (mono dim)
    sig = " · ".join(p for p in [code, cat] if p)
    d.text((P, meta_y), sig, font=_mono(25, 500), fill=INK_DIM)

    # venue + price chip (flat, hairline): pin · venue ............ price
    chip = [P, chip_y, W - P, chip_y + chip_h]
    d.rectangle(chip, fill=(255, 255, 255, 10))
    d.rectangle(chip, outline=INK_LINE, width=2)
    cy = chip_y + chip_h // 2
    _pin_sm(d, P + 30, cy - 4, 13)
    venue = str(item.get("venue") or "").strip()
    vf = _grotesk(31, 600)
    price = item.get("price_min")
    price_str = "бесплатно" if price is not None and float(price) == 0 else \
        (f"от {int(float(price))} ₽" if price is not None else "")
    pf = _mono(27, 600)
    pw = d.textlength(price_str, font=pf) if price_str else 0
    vmax = (W - P - 24 - (pw + 28 if pw else 0)) - (P + 58)
    vv = venue
    while vv and d.textlength(vv + "…", font=vf) > vmax:
        vv = vv[:-1]
    if vv != venue and vv:
        vv = vv.rstrip() + "…"
    d.text((P + 58, cy - 21), vv or "—", font=vf, fill=WHITE)
    if price_str:
        d.text((W - P - 24 - pw, cy - 18), price_str, font=pf, fill=ACID)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def _event_photo_bytes(event_id: str, src_url: str | None) -> bytes | None:
    """Photo bytes for an event: the ORIGINAL full-res source first (sharpest), our MinIO cache as
    the fallback. SSRF-guarded. None when neither is usable (caller falls back to a text DM)."""
    if src_url and is_public_http_url(src_url):
        try:
            r = httpx.get(src_url, timeout=8, follow_redirects=False, headers={"User-Agent": "okrest-card/1.0"})
            r.raise_for_status()
            return r.content
        except Exception:
            pass
    try:
        direct = get_object(f"events/{event_id}.jpg")
        if direct:
            return direct[0]
    except Exception:
        pass
    return None


def build_reminder_card(item: dict) -> bytes | None:
    """Render the composed reminder card from a live item (must carry a 'when' string). Fetches the
    event photo, then renders. Returns JPEG bytes, or None on failure (caller sends a text DM)."""
    photo = _event_photo_bytes(str(item.get("event_id")), item.get("image_primary") or item.get("image"))
    try:
        return render_reminder_card(item, photo)
    except Exception:
        logger.warning("reminder card render failed for %s", item.get("event_id"), exc_info=True)
        return None


# --- weekly digest poster: a VITRINE contact-sheet of the weekend's covers -----------
def _digest_tile(w: int, h: int, item: dict) -> Image.Image:
    """One catalogue tile: the cover (darkened, cover-fit), a bottom scrim, the accession code
    top-left, and the when + title bottom — the EventListRow look as a flat image."""
    photo = item.get("photo")
    tile = Image.new("RGB", (w, h), INK)
    if photo:
        try:
            ph = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (w, h), Image.LANCZOS)
            ph = ImageEnhance.Brightness(ph).enhance(0.66)
            ph = ImageEnhance.Color(ph).enhance(0.9)
            tile.paste(ph, (0, 0))
        except Exception:
            pass
    d = ImageDraw.Draw(tile, "RGBA")
    gh = int(h * 0.66)  # bottom legibility gradient
    for i in range(gh):
        d.line([(0, h - gh + i), (w, h - gh + i)], fill=(11, 11, 11, int(225 * (i / gh) ** 1.5)))
    pad = 16
    code = (item.get("code") or "").strip()
    if code:
        cf = _font(23, 600)
        cw = d.textlength(code, font=cf)
        d.rounded_rectangle([14, 14, 14 + cw + 18, 14 + 36], radius=3, fill=(11, 11, 11, 205))
        d.text((14 + 9, 14 + 7), code, font=cf, fill=ACID)
    title = (item.get("title") or "Событие").strip()
    tf = _font(27, 800)
    lines = _wrap(d, title, tf, w - 2 * pad, 2)
    lh = 32
    ty = h - pad - len(lines) * lh
    when = (item.get("when") or "").upper().strip()
    if when:
        wf = _font(16, 600)
        ww = w - 2 * pad
        while when and d.textlength(when + "…", font=wf) > ww:
            when = when[:-1]
        d.text((pad, ty - 25), when.rstrip(), font=wf, fill=ACID)
    for ln in lines:
        d.text((pad, ty), ln, font=tf, fill=(255, 255, 255))
        ty += lh
    d.rectangle([0, 0, w - 1, h - 1], outline=INK, width=2)
    return tile


def render_digest_poster(items: list[dict], label: str) -> bytes:
    """The weekly digest as ONE poster: окрест header + 'афиша на выходные' + the dates, then a
    2-column contact sheet of up to 6 weekend covers. items: {code,title,when,photo:bytes|None}."""
    img = Image.new("RGB", (W, H), PLASTER)
    d = ImageDraw.Draw(img)
    M = 30
    # header — wordmark, title, dates, acid rule
    _pin(d, M + 14, 54, 17)
    d.text((M + 42, 34), "окрест", font=_font(38, 800), fill=INK)
    d.line([W - M - 26, 42, W - M, 42], fill=CINNABAR, width=4)
    d.line([W - M, 42, W - M, 68], fill=CINNABAR, width=4)
    tf = _font(76, 800)
    d.text((M, 104), "афиша на", font=tf, fill=INK)
    d.text((M, 186), "выходные", font=tf, fill=INK)
    d.text((M, 286), (label or "").upper(), font=_font(30, 600), fill=CINNABAR)
    d.rectangle([M, 340, W - M, 347], fill=ACID)
    # grid
    items = [it for it in items if it][:6]
    cols = 2
    rows = max(1, (len(items) + 1) // 2)
    gut = 12
    gy0 = 366
    tw = (W - 2 * M - gut) // 2
    th = ((H - 78) - gy0 - gut * (rows - 1)) // rows
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        img.paste(_digest_tile(tw, th, it), (M + c * (tw + gut), gy0 + r * (th + gut)))
    # footer + outer frame
    d.text((M, H - 56), "СОБЫТИЯ РЯДОМ · @okrestmap_bot", font=_font(21, 600), fill=INK_DIM)
    d.rectangle([14, 14, W - 15, H - 15], outline=INK, width=3)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def ensure_card(event_id: str, title: str, meta: str, category: str, image_url: str) -> str:
    """Return the public URL of the cached card, rendering + storing it if needed."""
    key = f"cards/{event_id}.jpg"
    try:
        if object_exists(key):
            return public_url(key)
    except Exception:
        pass

    photo: bytes | None = None
    # Fast path: our own cached copy straight from MinIO (no network round-trip).
    try:
        direct = get_object(f"events/{event_id}.jpg")
        if direct:
            photo = direct[0]
    except Exception:
        photo = None
    # Otherwise fetch the source image — SSRF-guarded, it can come from a feed.
    if photo is None and image_url and is_public_http_url(image_url):
        try:
            r = httpx.get(image_url, timeout=8, follow_redirects=False, headers={"User-Agent": "okrest-card/1.0"})
            r.raise_for_status()
            photo = r.content
        except Exception:
            photo = None

    try:
        data = render_card(title, meta, category, photo)
        ensure_bucket()
        put_image(key, data, "image/jpeg")
        return public_url(key)
    except Exception:
        logger.warning("card render failed for %s", event_id, exc_info=True)
        return ""
