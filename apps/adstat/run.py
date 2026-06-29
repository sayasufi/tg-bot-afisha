"""Standalone-раннер скрапера adstat.

Примеры:
  python -m apps.adstat.run --dry-run kudago mscculture   # скрап без записи в БД (печать JSON)
  python -m apps.adstat.run kudago mscculture             # скрап + запись в adstat
  python -m apps.adstat.run                               # все активные adstat.targets → БД

Куки: ADSTAT_COOKIES_PATH (Netscape-экспорт залогиненной сессии). Запись в БД требует ADSTAT_ENABLED=true.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from apps.adstat.service import scrape


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows-консоль печатает кириллицу/эмодзи без падений
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="adstat channel scraper")
    ap.add_argument("usernames", nargs="*", help="@username каналов (пусто → активные adstat.targets)")
    ap.add_argument("--discover", action="store_true", help="автопоиск афиша-каналов (Telemetr) → targets + снимки")
    ap.add_argument("--telega", action="store_true", help="discovery через Telega.in (каталог афиши + цены)")
    ap.add_argument("--telethon", action="store_true", help="discovery через рекомендации Telegram (Telethon, бесплатно)")
    ap.add_argument("--score", action="store_true", help="ранжировать каналы: брать/осторожно/мимо")
    ap.add_argument("--enrich-prices", action="store_true", help="добрать цены telega по топ-афише без CPM")
    ap.add_argument("--top-n", type=int, default=50, help="сколько топ-афиша каналов добивать ценой")
    ap.add_argument("--min-subs", type=int, default=2000, help="порог подписчиков для Telemetr-discovery")
    ap.add_argument("--max-pages", type=int, default=60, help="страниц каталога Telega.in")
    ap.add_argument("--max-channels", type=int, default=400, help="лимит каналов для Telethon-крауля")
    ap.add_argument("--no-prices", action="store_true", help="Telega: без подкачки цен (быстрее)")
    ap.add_argument("--dry-run", action="store_true", help="не писать в БД, напечатать результаты")
    args = ap.parse_args()

    if args.score:
        from apps.adstat.score import rank
        rows = rank(limit=40)
        print("%-22s %5s %-10s %8s %5s %8s  причина" % ("канал", "скор", "вердикт", "охват", "ER", "CPM"))
        for r in rows:
            print("%-22s %5s %-10s %8s %5s %8s  %s" % (
                r["username"], r["score"], r["verdict"], r.get("reach"), r.get("er"), r.get("cpm"), r["reason"]))
        return

    if args.enrich_prices:
        from apps.adstat.discover import enrich_shortlist_prices
        n = enrich_shortlist_prices(top_n=args.top_n, dry_run=args.dry_run)
        print(f"adstat enrich-prices: {n} афиша-каналов получили цену → score обновится")
        return

    if args.telethon:
        from apps.adstat.telethon_src import discover_telethon
        n = discover_telethon(max_channels=args.max_channels, dry_run=args.dry_run)
        print(f"adstat telethon: записано {n} каналов → targets + снимки")
        return

    if args.telega:
        from apps.adstat.discover import discover_telega
        rows = discover_telega(max_pages=args.max_pages, with_prices=not args.no_prices, dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        else:
            withp = sum(1 for r in rows if r.get("post_price"))
            print(f"adstat telega: {len(rows)} каналов ({withp} с ценой) → targets + снимки")
        return

    if args.discover:
        from apps.adstat.discover import discover
        rows = discover(min_subscribers=args.min_subs, dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"adstat discover: {len(rows)} каналов → targets + снимки")
        return

    rows = scrape(usernames=args.usernames or None, dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    else:
        ok = sum(1 for r in rows if not r.get("error"))
        print(f"adstat: {ok}/{len(rows)} снимков записано")


if __name__ == "__main__":
    main()
