"""One-time interactive login to mint a Telethon StringSession for reading PUBLIC channels (no joining).

Run it ON THE SERVER (where .env lives), in an interactive container so it can prompt you:

    docker compose run --rm -it prefect-serve python scripts/telethon_login.py

It asks for your api_id / api_hash (from https://my.telegram.org → API development tools), your phone,
and the login code Telegram sends you (plus your 2FA password if you have one), then writes
TELETHON_API_ID / TELETHON_API_HASH / TELETHON_SESSION into .env. The session string is NOT printed.
Afterwards: `docker compose restart prefect-serve`. The session reads public channels without joining;
to revoke it later, log it out from Telegram → Settings → Devices.
"""
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

ENV_PATH = os.environ.get("ENV_PATH", "/app/.env")  # .env is bind-mounted at /app via the compose `.:/app`


def _upsert_env(path: str, updates: dict[str, str]) -> None:
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    keys = set(updates)
    kept = [ln for ln in lines if (ln.split("=", 1)[0].strip() if "=" in ln else "") not in keys]
    kept += [f"{k}={v}" for k, v in updates.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + "\n")


def main() -> None:
    api_id = input("api_id (my.telegram.org): ").strip()
    api_hash = input("api_hash: ").strip()
    phone = input("phone (+7...): ").strip()
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    client.start(phone=phone)  # interactive: prompts for the login code (+ 2FA password) as needed
    session = client.session.save()
    me = client.get_me()
    client.disconnect()
    _upsert_env(ENV_PATH, {
        "TELETHON_API_ID": api_id,
        "TELETHON_API_HASH": api_hash,
        "TELETHON_SESSION": session,
    })
    print(f"OK — logged in as {getattr(me, 'username', None) or me.id}; session ({len(session)} chars) written to {ENV_PATH}.")
    print("Now run: docker compose restart prefect-serve")


if __name__ == "__main__":
    main()
