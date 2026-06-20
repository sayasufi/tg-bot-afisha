"""One-off backfill: arm reminders for all EXISTING favourites.

The reminder model changed — favourites now drive reminders (the per-event bell is gone). New
favourites arm a reminder via the API, but events favourited BEFORE this change have none. This
arms one for every future-dated favourite of every user who has notifications on. Idempotent
(set_reminder upserts on (user, event)), so it's safe to re-run.

    docker compose exec -T api python -m scripts.backfill_favorite_reminders
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from core.db.models.ref.user import User
from core.db.repositories.reminders import arm_reminder_if_unsent, soonest_future_start
from core.db.repositories.users import list_favorite_ids
from core.db.session import WorkerAsyncSessionLocal

_LEAD = timedelta(hours=2)


async def main() -> None:
    armed = 0
    async with WorkerAsyncSessionLocal() as db:
        uids = (
            await db.execute(select(User.telegram_user_id).where(User.notify_reminders.is_(True)))
        ).scalars().all()
        now = datetime.now(timezone.utc)
        for uid in uids:
            for fid in await list_favorite_ids(db, uid):
                start = await soonest_future_start(db, fid)
                if start is None:
                    continue  # no UPCOMING session → nothing to remind about (never arm a past event)
                # Non-destructive: don't resurrect a reminder that already fired.
                await arm_reminder_if_unsent(db, uid, fid, max(now + timedelta(seconds=45), start - _LEAD))
                armed += 1
        await db.commit()
    print(f"armed {armed} reminders across {len(uids)} notify-on users")


if __name__ == "__main__":
    asyncio.run(main())
