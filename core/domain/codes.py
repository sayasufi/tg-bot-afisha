"""Public, URL-safe event codes — "MSK-04PN".

A stored per-event sequence (``events.display_no``) Crockford-base32 encoded and
prefixed with a city code. Properties we want and get:
  * unique BY CONSTRUCTION (it's a sequence) — no hash collisions at any scale;
  * short even at millions of events (1e6 -> 4 base32 chars);
  * Latin / URL-safe, so a future ``/e/<code>`` short link drops straight in;
  * reversible — ``parse_event_code`` decodes back to (city, display_no) so that
    future route resolves to the exact event with one indexed lookup;
  * stable — tied 1:1 to the event row, never derived from a lossy hash.

Crockford base32 omits I, L, O, U (no visual ambiguity) and maps them to their
look-alikes on decode, so a human who types "MSK-O4PN" still resolves correctly.
"""

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # 32 unambiguous symbols (no I L O U)
_DECODE = {c: i for i, c in enumerate(_CROCKFORD)}
_DECODE.update({"I": 1, "L": 1, "O": 0, "U": 0})  # forgive the dropped look-alikes

_DEFAULT_CITY_CODE = "MSK"


def city_code(city: str | None) -> str:
    """Airport-style prefix ("MSK") for a city given by display name ("Москва") OR slug
    ("moscow"). Resolved from the core.domain.cities registry — the single source of truth
    for all 16 cities — so codes never go stale as cities are added. Was a hand-kept parallel
    dict that covered only 6/16 (the other 10 silently fell back to MSK, cross-linking events)."""
    # Local import keeps this module importable without pulling the whole city registry when a
    # caller only needs the pure encode/decode helpers, and avoids any import cycle.
    from core.domain.cities import city_by_name

    cfg = city_by_name(city)
    return cfg.code if cfg is not None else _DEFAULT_CITY_CODE


def encode_no(n: int, width: int = 4) -> str:
    """Crockford-base32 of a positive int, left-padded to ``width`` for a steady
    look (1 -> '0001', 4821 -> '04PN')."""
    if n is None or n <= 0:
        return "0" * width
    out: list[str] = []
    while n > 0:
        out.append(_CROCKFORD[n & 31])
        n >>= 5
    return "".join(reversed(out)).rjust(width, "0")


def decode_no(s: str) -> int:
    n = 0
    for ch in (s or "").strip().upper():
        if ch in "-· ":
            continue
        if ch not in _DECODE:
            raise ValueError(f"bad code char: {ch!r}")
        n = (n << 5) | _DECODE[ch]
    return n


def event_code(display_no: int | None, city: str | None = None) -> str | None:
    """"MSK-04PN" for the sheet/links, or None if the event has no number yet."""
    if display_no is None:
        return None
    return f"{city_code(city)}-{encode_no(display_no)}"


def parse_event_code(code: str) -> tuple[str, int]:
    """'MSK-04PN' (or 'msk·04pn') -> ('MSK', 4821). For a future /e/<code> route."""
    raw = (code or "").strip().upper().replace("·", "-").replace(" ", "")
    city, sep, rest = raw.partition("-")
    if not sep:  # no city prefix — treat the whole thing as the number
        city, rest = _DEFAULT_CITY_CODE, city
    return (city or _DEFAULT_CITY_CODE), decode_no(rest)
