import re
from typing import TYPE_CHECKING

from connectors.base import RawRecord

if TYPE_CHECKING:
    from core.db.models import IngestInbox


class ForwardInboxConnector:
    source_name = "telegram_forward_inbox"
    _URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _HASHTAG_RE = re.compile(r"#([\w\d_]+)", re.IGNORECASE)
    _TEXT_LIMIT = 12000

    async def fetch(self, cursor: str | None = None):
        # Pull-based connector placeholder; consumed directly in worker task from ingest_inbox table.
        return [], cursor

    @staticmethod
    def _extract_forward_message_url(payload: dict) -> str:
        fchat = payload.get("forward_from_chat") if isinstance(payload.get("forward_from_chat"), dict) else {}
        username = fchat.get("username")
        fmsg_id = payload.get("forward_from_message_id")
        if username and fmsg_id:
            return f"https://t.me/{username}/{fmsg_id}"
        return ""

    @staticmethod
    def _extract_images(payload: dict) -> list[str]:
        images: list[str] = []
        photo = payload.get("photo")
        if isinstance(photo, list):
            for item in photo:
                if isinstance(item, dict):
                    file_id = item.get("file_id")
                    if file_id:
                        images.append(str(file_id))
        if isinstance(payload.get("photo"), dict):
            file_id = payload["photo"].get("file_id")
            if file_id:
                images.append(str(file_id))
        if isinstance(payload.get("image"), str):
            images.append(payload["image"])
        return list(dict.fromkeys(images))

    @staticmethod
    def to_raw_record(inbox: "IngestInbox") -> RawRecord:
        payload = inbox.payload_json if isinstance(inbox.payload_json, dict) else {}
        text = str(payload.get("text") or payload.get("caption") or "").strip()
        urls = list(dict.fromkeys(ForwardInboxConnector._URL_RE.findall(text)))
        tags = [tag.lower() for tag in ForwardInboxConnector._HASHTAG_RE.findall(text)]
        source_url = ForwardInboxConnector._extract_forward_message_url(payload)
        trimmed_payload = {
            "id": inbox.telegram_message_id,
            "source": "telegram_forward_inbox",
            "chat_id": inbox.chat_id,
            "published_at": payload.get("date"),
            "title": text.splitlines()[0][:200] if text else "",
            "description": text[: ForwardInboxConnector._TEXT_LIMIT],
            "site_url": source_url,
            "images": ForwardInboxConnector._extract_images(payload),
            "url_entities": urls,
            "tags": list(dict.fromkeys(tags)),
        }
        return RawRecord(
            external_id=f"forward:{inbox.chat_id}:{inbox.telegram_message_id}",
            payload=trimmed_payload,
            raw_text=trimmed_payload["description"],
        )
