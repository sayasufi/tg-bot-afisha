"""Render a branded VITRINE share card (PNG) for an event and cache it in MinIO."""
import io
import logging
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
    "standup": "Стендап",
    "festival": "Фестиваль",
    "lecture": "Лекция",
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
    # Ellipsize the last line if we ran out of room.
    if lines:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        if len("".join(lines)) < len(text.replace(" ", "")) and last != lines[-1]:
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
    img.save(out, "PNG")
    return out.getvalue()


def ensure_card(event_id: str, title: str, meta: str, category: str, image_url: str) -> str:
    """Return the public URL of the cached card, rendering + storing it if needed."""
    key = f"cards/{event_id}.png"
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
            r = httpx.get(image_url, timeout=15, follow_redirects=False, headers={"User-Agent": "okrest-card/1.0"})
            r.raise_for_status()
            photo = r.content
        except Exception:
            photo = None

    try:
        png = render_card(title, meta, category, photo)
        ensure_bucket()
        put_image(key, png, "image/png")
        return public_url(key)
    except Exception:
        logger.warning("card render failed for %s", event_id, exc_info=True)
        return ""
