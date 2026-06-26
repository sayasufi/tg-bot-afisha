"""Импорт Telethon-аккаунта в пул adstat.tg_accounts.

Конвертирует .session-файл (SQLite) в StringSession ОФФЛАЙН (без логина) и кладёт в БД.
.session-файл — секрет, в репозиторий не кладём (лежит в secrets/ на сервере).

Запуск в контейнере (prefect-serve):
  # .env-сессия как acc1:
  python scripts/adstat_import_account.py --env-acc1
  # купленный/свой аккаунт из .session:
  python scripts/adstat_import_account.py --session /app/secrets/acc2 --label 13377773758 \
      --api-id 2040 --api-hash <hash> --note "TeleRaptor 2021"
"""
import argparse

from sqlalchemy import select

from core.config.settings import get_settings
from core.db.models.adstat import AdTgAccount
from core.db.session import SessionLocal


def _upsert(label: str, session: str, api_id: int | None, api_hash: str | None, note: str) -> None:
    with SessionLocal() as db:
        ex = db.execute(select(AdTgAccount).where(AdTgAccount.label == label)).scalar_one_or_none()
        if ex:
            ex.session, ex.api_id, ex.api_hash, ex.is_active = session, api_id, api_hash, True
        else:
            db.add(AdTgAccount(label=label, session=session, api_id=api_id, api_hash=api_hash, note=note))
        db.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="путь к .session (без расширения), например /app/secrets/acc2")
    ap.add_argument("--label")
    ap.add_argument("--api-id", type=int)
    ap.add_argument("--api-hash")
    ap.add_argument("--note", default="imported")
    ap.add_argument("--env-acc1", action="store_true", help="импортировать .env TELETHON_SESSION как acc1-env")
    a = ap.parse_args()
    s = get_settings()

    if a.env_acc1 and s.telethon_session:
        _upsert("acc1-env", s.telethon_session, None, None, "основная .env сессия")
        print("acc1-env импортирован")

    if a.session:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(a.session, a.api_id, a.api_hash)  # грузит SQLite-сессию, БЕЗ connect
        ss = StringSession.save(client.session)
        _upsert(a.label, ss, a.api_id, a.api_hash, a.note)
        print(f"{a.label} импортирован (StringSession len={len(ss)})")

    with SessionLocal() as db:
        rows = db.execute(select(AdTgAccount.label, AdTgAccount.is_active, AdTgAccount.api_id)).all()
        print("пул аккаунтов:", [(r[0], r[1]) for r in rows])


if __name__ == "__main__":
    main()
