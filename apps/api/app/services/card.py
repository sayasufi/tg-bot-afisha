"""Render a branded VITRINE share card (PNG) for an event and cache it in MinIO."""
import io
import logging
import math
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

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


def _pin_sm(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color=INK, hole=ACID) -> None:
    """The окрест brand pin, traced to the app avatar: a round map-pin head with a CONCENTRIC ring
    (a `hole`-coloured gap + a `color` centre dot), and a body that tapers SMOOTHLY — its sides are
    tangent to the head circle — down to a point. Defaults match the avatar: ink pin, acid gap, ink
    dot. Head centred at (cx, cy)."""
    h = r * 1.8                              # tip distance below the head centre (avatar proportion)
    ty = cy + r * r / h                      # tangent chord — where the body meets the head smoothly
    tx = r * math.sqrt(h * h - r * r) / h
    d.polygon([(cx - tx, ty), (cx, cy + h), (cx + tx, ty)], fill=color)   # body: tangent sides → point
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)              # head disc
    gr = r * 0.64                            # concentric gap (leaves the head as a ring)
    d.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=hole)
    dr = r * 0.18                            # centre dot
    d.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill=color)


def _calendar(d: ImageDraw.ImageDraw, x: float, y: float, s: float, color) -> None:
    """A small calendar glyph — the share card's 'date' lead mark. Size s, top-left at (x, y)."""
    r = max(2, int(s * 0.1))
    d.rounded_rectangle([x, y + s * 0.16, x + s * 0.9, y + s], radius=int(s * 0.12), outline=color, width=r)
    d.line([x, y + s * 0.40, x + s * 0.9, y + s * 0.40], fill=color, width=r)             # header divider
    d.line([x + s * 0.26, y, x + s * 0.26, y + s * 0.26], fill=color, width=r)            # left binding ring
    d.line([x + s * 0.64, y, x + s * 0.64, y + s * 0.26], fill=color, width=r)            # right binding ring


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


# --- composed VITRINE card: ONE fixed 1080×1280 frame shared by the reminder DM and the share image
# so they look identical. A bright photo hero (code tab · окрест wordmark · cinnabar tick) over a LIGHT
# plaster body — a lead line, the title, code · category, and a venue+price chip. Only the lead varies:
# a cinnabar bolt + relative «через 2 часа» for a reminder, an ink calendar + the event date for a
# share. Type: Unbounded wordmark · Golos Text title · Martian Mono data. Size is FIXED so the image
# never changes dimensions between sends; the chip is bottom-anchored and the text block centred, so a
# 1-line and a 3-line title both look balanced without resizing.
def _compose_card(item: dict, photo: bytes | None, lead_text: str, lead_mark: str = "bolt",
                  lead_color=CINNABAR) -> bytes:
    W, P, PH, RULE = 1080, 46, 700, 6
    LH, chip_h, H = 72, 78, 1280

    # photo hero — kept BRIGHT (only a bottom scrim for the wordmark); cover-fit, acid fallback.
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

    # LIGHT plaster body; chip bottom-anchored, text block (lead · title · meta) vertically centred.
    title = str(item.get("title") or "Событие").strip()
    tf = _grotesk(62, 700)
    chip_y = H - P - chip_h
    img = Image.new("RGB", (W, H), PLASTER)
    img.paste(block, (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, PH, W, PH + RULE], fill=ACID)

    tlines = _wrap(d, title, tf, W - 2 * P, 3)
    lead = (lead_text or "").strip()
    LEAD_H, LEAD_GAP = (38, 30) if lead else (0, 0)
    META_GAP, META_H = 16, 30
    block_h = LEAD_H + LEAD_GAP + len(tlines) * LH + META_GAP + META_H
    region_top, region_bottom = PH + RULE + 24, chip_y - 24
    y = region_top + max(0, (region_bottom - region_top - block_h) // 2)

    if lead:  # lead: a mark + relative-when (reminder) / event-date (share), mono
        if lead_mark == "calendar":
            _calendar(d, P, y + 2, 34, lead_color)
        else:
            _bolt(d, P, y, 38, lead_color)
        d.text((P + 48, y + 3), lead, font=_mono(28, 500), fill=lead_color)
        y += LEAD_H + LEAD_GAP
    for ln in tlines:  # title (grotesk bold, ink)
        d.text((P, y), ln, font=tf, fill=INK)
        y += LH
    y += META_GAP
    cat = CAT_LABEL.get(item.get("category") or "", "Событие").upper()  # code · category (mono dim)
    sig = " · ".join(p for p in [code, cat] if p)
    d.text((P, y), sig, font=_mono(25, 500), fill=INK_DIM)

    # venue + price chip (flat, ink hairline): pin · venue ............ price
    chip = [P, chip_y, W - P, chip_y + chip_h]
    d.rectangle(chip, outline=INK, width=2)
    cy = chip_y + chip_h // 2
    _pin_sm(d, P + 32, cy - 7, 15)  # ink pin · acid ring · ink dot (avatar)
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
    d.text((P + 58, cy - 21), vv or "—", font=vf, fill=INK)
    if price_str:
        d.text((W - P - 24 - pw, cy - 18), price_str, font=pf, fill=INK)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def render_reminder_card(item: dict, photo: bytes | None) -> bytes:
    """Reminder DM card — relative «через N часов» urgency lead (cinnabar bolt)."""
    return _compose_card(item, photo, str(item.get("when") or ""), "bolt", CINNABAR)


def render_share_card(item: dict, photo: bytes | None) -> bytes:
    """Share image — the same card with the event DATE as the lead (ink calendar, no urgency)."""
    return _compose_card(item, photo, str(item.get("when") or ""), "calendar", INK)


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
    """One weekend event as a MINI light card — the same language as the reminder/share card: a BRIGHT
    cover with the code tab + an acid rule, then a plaster caption with the when (mono) and the title
    (Golos). items carry {code, title, when, photo:bytes|None}."""
    ph = int(h * 0.60)  # cover height; the rest is the plaster caption
    RULE = 4
    tile = Image.new("RGB", (w, h), PLASTER)
    photo = item.get("photo")
    block = Image.new("RGB", (w, ph), ACID)
    if photo:
        try:
            block = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (w, ph), Image.LANCZOS)
        except Exception:
            block = Image.new("RGB", (w, ph), ACID)
    tile.paste(block, (0, 0))
    d = ImageDraw.Draw(tile, "RGBA")
    code = (item.get("code") or "").strip()
    if code:  # accession code, top-left ink tab (mono acid)
        cf = _mono(20, 600)
        cw = d.textlength(code, font=cf); pad = 9
        d.rectangle([12, 12, 12 + cw + 2 * pad, 48], fill=(11, 11, 11, 220))
        d.text((12 + pad, 19), code, font=cf, fill=ACID)
    d.rectangle([0, ph, w, ph + RULE], fill=ACID)  # acid rule under the cover
    P = 16
    cy = ph + RULE + 13
    when = (item.get("when") or "").strip()
    if when:  # mono, cinnabar, ellipsized
        wf = _mono(18, 500)
        full = when
        while when and d.textlength(when + "…", font=wf) > w - 2 * P:
            when = when[:-1]
        if when != full and when:
            when = when.rstrip() + "…"
        d.text((P, cy), when, font=wf, fill=CINNABAR)
        cy += 27
    tf = _grotesk(26, 700)  # title (Golos bold ink)
    for ln in _wrap(d, (item.get("title") or "Событие").strip(), tf, w - 2 * P, 2):
        d.text((P, cy), ln, font=tf, fill=INK)
        cy += 31
    d.rectangle([0, 0, w - 1, h - 1], outline=INK, width=2)  # tile hairline
    return tile


def render_digest_poster(items: list[dict], label: str) -> bytes:
    """The weekly digest as ONE light VITRINE poster — the same language as the cards: the окрест
    lockup (avatar pin + wordmark) + cinnabar tick + acid rule, then a 2-column grid of mini event
    cards. items carry {code, title, when, photo:bytes|None}."""
    img = Image.new("RGB", (W, H), PLASTER)
    d = ImageDraw.Draw(img, "RGBA")
    M = 30
    # brand lockup — avatar pin + окрест wordmark + cinnabar registration tick
    _pin_sm(d, M + 13, 50, 15)
    d.text((M + 42, 30), "окрест", font=_font(38, 800), fill=INK)
    d.line([W - M - 30, 42, W - M, 42], fill=CINNABAR, width=5)
    d.line([W - M, 42, W - M, 72], fill=CINNABAR, width=5)
    # heading (Golos, like the card titles) + dates (mono) + acid rule
    hf = _grotesk(80, 700)
    d.text((M, 92), "афиша на", font=hf, fill=INK)
    d.text((M, 184), "выходные", font=hf, fill=INK)
    d.text((M, 290), (label or "").upper(), font=_mono(28, 600), fill=CINNABAR)
    d.rectangle([M, 340, W - M, 347], fill=ACID)
    # grid of mini cards
    items = [it for it in items if it][:6]
    cols = 2
    rows = max(1, (len(items) + 1) // 2)
    gut = 14
    gy0 = 368
    foot = 62
    tw = (W - 2 * M - gut) // 2
    th = ((H - foot) - gy0 - gut * (rows - 1)) // rows
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        img.paste(_digest_tile(tw, th, it), (M + c * (tw + gut), gy0 + r * (th + gut)))
    # footer (mono, dim)
    d.text((M, H - 46), "СОБЫТИЯ РЯДОМ · @OKRESTMAP_BOT", font=_mono(19, 500), fill=INK_DIM)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def ensure_card(event_id: str, item: dict, image_url: str) -> str:
    """Public URL of the cached unified share card (rendered + stored if missing). `item` carries
    code / title / category / venue / price_min / when (the event DATE). Empty string on failure.
    The card is STATIC (an absolute date, not a relative time), so it's safe to cache per event."""
    key = f"cards/v4/{event_id}.jpg"  # v4: avatar-traced ink pin + acid ring, ink price (v3 = acid chip)
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
        data = render_share_card(item, photo)
        ensure_bucket()
        put_image(key, data, "image/jpeg")
        return public_url(key)
    except Exception:
        logger.warning("card render failed for %s", event_id, exc_info=True)
        return ""
