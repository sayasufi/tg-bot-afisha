"""QR-code Telethon login — for when the in-app login code can't be read.

  python scripts/telethon_login_qr.py <api_id> <api_hash> [2fa_password]

Renders a login QR to MinIO (printed as QR_URL: <url>), then waits for you to scan it in the
account's app (Settings → Devices → Link Desktop Device → scan). Re-creates the QR every ~25s as
the token expires (refresh the page to see the new one). On success writes TELETHON_API_ID/HASH/
SESSION to .env. Run in the background and read QR_URL from its output. No joining required.
"""
import asyncio
import io
import os
import sys

import boto3
import segno
from botocore.client import Config
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from core.config.settings import get_settings
from core.media.storage import ensure_bucket

API_ID = sys.argv[1]
API_HASH = sys.argv[2]
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else None
ENV_PATH = os.environ.get("ENV_PATH", "/app/.env")
KEY = "telegram/login_qr.png"


def _s3():
    s = get_settings()
    return boto3.client("s3", endpoint_url=s.minio_endpoint, aws_access_key_id=s.minio_access_key,
                        aws_secret_access_key=s.minio_secret_key, config=Config(signature_version="s3v4"),
                        region_name="us-east-1")


def upload_qr(url: str) -> str:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=9, border=4)
    s = get_settings()
    _s3().put_object(Bucket=s.minio_bucket, Key=KEY, Body=buf.getvalue(), ContentType="image/png",
                     CacheControl="no-store, max-age=0")
    base = s.media_public_base.rstrip("/") or "/v1/media"
    return f"{base}/{KEY}"


def _upsert_env(path: str, updates: dict) -> None:
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    keys = set(updates)
    kept = [ln for ln in lines if (ln.split("=", 1)[0].strip() if "=" in ln else "") not in keys]
    kept += [f"{k}={v}" for k, v in updates.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + "\n")


async def main():
    ensure_bucket()
    client = TelegramClient(StringSession(), int(API_ID), API_HASH)
    await client.connect()
    qr = await client.qr_login()
    print("QR_URL:", upload_qr(qr.url), flush=True)
    print("Scan in @fffgergerg: Settings > Devices > Link Desktop Device. Refresh the page if it expires.", flush=True)
    authed = False
    for _ in range(14):  # ~14 * 25s ≈ 5.5 min
        try:
            await qr.wait(timeout=25)
            authed = True
            break
        except asyncio.TimeoutError:
            await qr.recreate()
            upload_qr(qr.url)
        except SessionPasswordNeededError:
            if not PASSWORD:
                print("2FA_REQUIRED — re-run with the 2FA password as the 3rd arg", flush=True)
                await client.disconnect()
                return
            await client.sign_in(password=PASSWORD)
            authed = True
            break
    if not authed:
        print("TIMEOUT — re-run", flush=True)
        await client.disconnect()
        return
    session = client.session.save()
    me = await client.get_me()
    await client.disconnect()
    _upsert_env(ENV_PATH, {"TELETHON_API_ID": str(API_ID), "TELETHON_API_HASH": API_HASH, "TELETHON_SESSION": session})
    print("OK — logged in as", getattr(me, "username", None) or me.id, "— session written to", ENV_PATH, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
