"""Two-step NON-interactive Telethon login, for driving over a plain (non-TTY) ssh.

  python scripts/telethon_login_driver.py step1 <api_id> <api_hash> <phone>
  python scripts/telethon_login_driver.py step2 <code> [2fa_password]

step1 requests the login code (Telegram delivers it to the account) and stashes a partial session +
phone_code_hash in a temp file. step2 signs in with the code you read from Telegram and writes
TELETHON_API_ID/HASH/SESSION into .env, then deletes the temp file. The session string is never printed.
"""
import asyncio
import json
import os
import sys

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

ENV_PATH = os.environ.get("ENV_PATH", "/app/.env")
TMP_PATH = os.environ.get("TMP_PATH", "/app/.telethon_login_tmp.json")


def _upsert_env(path: str, updates: dict[str, str]) -> None:
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    keys = set(updates)
    kept = [ln for ln in lines if (ln.split("=", 1)[0].strip() if "=" in ln else "") not in keys]
    kept += [f"{k}={v}" for k, v in updates.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + "\n")


async def step1(api_id: str, api_hash: str, phone: str) -> None:
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.connect()
    sent = await client.send_code_request(phone)
    sess = client.session.save()
    await client.disconnect()
    with open(TMP_PATH, "w") as f:
        json.dump({"api_id": api_id, "api_hash": api_hash, "phone": phone,
                   "phone_code_hash": sent.phone_code_hash, "session": sess}, f)
    print(f"code requested for {phone} — read it from the account's Telegram, then run step2 <code>")


async def step2(code: str, password: str | None) -> None:
    with open(TMP_PATH) as f:
        d = json.load(f)
    client = TelegramClient(StringSession(d["session"]), int(d["api_id"]), d["api_hash"])
    await client.connect()
    try:
        await client.sign_in(d["phone"], code=code, phone_code_hash=d["phone_code_hash"])
    except SessionPasswordNeededError:
        if not password:
            await client.disconnect()
            print("2FA is on — re-run: step2 <code> <2fa_password>")
            return
        await client.sign_in(password=password)
    session = client.session.save()
    me = await client.get_me()
    await client.disconnect()
    _upsert_env(ENV_PATH, {"TELETHON_API_ID": d["api_id"], "TELETHON_API_HASH": d["api_hash"], "TELETHON_SESSION": session})
    os.remove(TMP_PATH)
    print(f"OK — logged in as {getattr(me, 'username', None) or me.id}; session ({len(session)} chars) written to {ENV_PATH}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "step1":
        asyncio.run(step1(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif cmd == "step2":
        asyncio.run(step2(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
    else:
        print("usage: step1 <api_id> <api_hash> <phone> | step2 <code> [2fa_password]")
