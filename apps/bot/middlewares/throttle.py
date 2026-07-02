"""Per-chat rate limiting for the bot.

The unauthenticated FORWARD path (forwarded.py) writes every forwarded post into the
ingestion queue, which then runs through the LLM classifier — so a single chat spamming
forwards floods the pipeline and burns tokens. This outer middleware caps how fast and how
often any one chat can drive message handlers, before a handler ever runs.

In-memory by design: the bot is a single long-lived polling process, so a plain dict of
timestamps is enough and avoids a hard Redis dependency on the hot path. State is per
process and resets on restart, which is fine for abuse-throttling.
"""
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

# Cooldown between two accepted messages from the same chat (seconds). Below this the
# message is silently dropped — no reply, so a flooder gets no feedback loop.
_COOLDOWN_SECONDS = 1.5
# Hard per-chat daily ceiling. Beyond it we stop processing for the rest of the UTC day
# and send a single short notice on the first over-limit hit.
_DAILY_CAP = 120


class ThrottleMiddleware(BaseMiddleware):
    """Outer message middleware: cooldown + per-chat daily cap, keyed by chat id."""

    def __init__(self, cooldown: float = _COOLDOWN_SECONDS, daily_cap: int = _DAILY_CAP) -> None:
        self.cooldown = cooldown
        self.daily_cap = daily_cap
        self._last_seen: dict[int, float] = {}
        # chat_id -> [utc_day, count, notified_over_cap]
        self._daily: dict[int, list] = defaultdict(lambda: [0, 0, False])

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        chat = getattr(event, "chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:  # nothing to key on → don't get in the way
            return await handler(event, data)

        # Never throttle non-text signals a handler must see: a shared location (город пишется
        # сразу после /start — cooldown иначе дропает его и город не сохраняется), a shared
        # contact, or a forwarded post. These aren't a flood vector the way free text is, and
        # dropping them silently breaks the flow.
        if (
            getattr(event, "location", None) is not None
            or getattr(event, "contact", None) is not None
            or getattr(event, "forward_origin", None) is not None
            or getattr(event, "forward_from_chat", None) is not None
        ):
            return await handler(event, data)

        now = time.monotonic()
        day = int(time.time() // 86400)
        state = self._daily[chat_id]
        if state[0] != day:  # new UTC day → reset the counter for this chat
            state[0], state[1], state[2] = day, 0, False

        # Daily cap: drop silently, but warn once so a real user understands the silence.
        if state[1] >= self.daily_cap:
            if not state[2]:
                state[2] = True
                await event.answer("Слишком много сообщений за сегодня — попробуй завтра.")
            return None

        # Cooldown: drop the message without a reply (no feedback to a flooder).
        last = self._last_seen.get(chat_id)
        if last is not None and now - last < self.cooldown:
            return None

        self._last_seen[chat_id] = now
        state[1] += 1
        return await handler(event, data)
