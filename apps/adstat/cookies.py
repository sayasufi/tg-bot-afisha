"""Загрузка кук залогиненной сессии из Netscape cookies.txt (экспорт расширением браузера).

Куки чувствительны — путь задаётся через ADSTAT_COOKIES_PATH, в репозиторий файл не кладём.
Telemetr нужна только сессия (PHPSESSID) — она не привязана к IP, переезжает на сервер.
TGStat дополнительно нужен cf_clearance (привязан к IP+UA, протухает) — см. README.
"""
from __future__ import annotations

import os


def load_netscape_cookies(path: str, domain_sub: str) -> dict[str, str]:
    """Вернуть {name: value} для кук, чей домен содержит ``domain_sub``."""
    jar: dict[str, str] = {}
    if not path or not os.path.exists(path):
        return jar
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            elif line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 7 and domain_sub in parts[0]:
                jar[parts[5]] = parts[6]
    return jar
