import { useEffect, useState } from "react";

import { inviteToFriend, manageFriends, type Friend } from "../../api/users";
import { haptic } from "../../lib/telegram";
import { showToast } from "../../lib/toast";
import { safeHttpUrl } from "../../lib/url";

// «Позвать друга» — pick a mutual friend to DM this event. Tapping a row invites that friend (they get
// «X зовёт тебя на <event>»); you can invite several, then close. Server-gated to mutual friends.
export function FriendPicker({ eventId, onClose }: { eventId: string; onClose: () => void }) {
  const [friends, setFriends] = useState<Friend[]>([]);
  const [loading, setLoading] = useState(true);
  const [invited, setInvited] = useState<Set<number>>(() => new Set());

  useEffect(() => {
    let alive = true;
    manageFriends().then((s) => {
      if (!alive) return;
      setFriends(s?.friends ?? []);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const invite = async (f: Friend) => {
    if (invited.has(f.id)) return;
    haptic("light");
    setInvited((s) => new Set(s).add(f.id)); // optimistic
    const res = await inviteToFriend(eventId, f.id);
    showToast(res?.sent ? `Позвали ${f.name || "друга"}` : "Уже звали или у друга выключены уведомления", {
      tone: res?.sent ? "good" : "muted",
    });
  };

  return (
    <div className="fdisc-veil" onClick={onClose}>
      <div className="fpick" role="dialog" aria-modal="true" aria-label="Позвать друга" onClick={(e) => e.stopPropagation()}>
        <div className="fpick__head">
          <span className="fdisc__kicker">позвать друга</span>
          <button type="button" className="fpick__x" aria-label="Закрыть" onClick={onClose}>
            ×
          </button>
        </div>
        {loading ? (
          <p className="profile__friends-empty">Загружаем…</p>
        ) : friends.length ? (
          <div className="fpick__list">
            {friends.map((f) => {
              const av = safeHttpUrl(f.photo_url);
              const done = invited.has(f.id);
              return (
                <button key={f.id} type="button" className="fpick__row" onClick={() => invite(f)} disabled={done}>
                  <span
                    className="profile__friend-av"
                    style={av ? { backgroundImage: `url("${av}")` } : undefined}
                  >
                    {av ? "" : (f.name || "?").slice(0, 1).toUpperCase()}
                  </span>
                  <span className="profile__friend-name">{f.name || "Друг"}</span>
                  <span className={`fpick__act${done ? " is-done" : ""}`}>{done ? "✓ позвали" : "позвать"}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="profile__friends-empty">Пока нет друзей — пригласи их в разделе «Друзья».</p>
        )}
      </div>
    </div>
  );
}
