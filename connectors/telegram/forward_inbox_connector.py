from connectors.base import RawRecord
from core.db.models import IngestInbox


class ForwardInboxConnector:
    source_name = "telegram_forward_inbox"

    async def fetch(self, cursor: str | None = None):
        # Pull-based connector placeholder; consumed directly in worker task from ingest_inbox table.
        return [], cursor

    @staticmethod
    def to_raw_record(inbox: IngestInbox) -> RawRecord:
        payload = inbox.payload_json
        text = payload.get("text") or payload.get("caption") or ""
        return RawRecord(external_id=f"forward:{inbox.chat_id}:{inbox.telegram_message_id}", payload=payload, raw_text=text)
