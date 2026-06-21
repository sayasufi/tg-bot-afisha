import { useEffect, useState } from "react";

import { acceptFriendLink, peekFriendLink, type Friend } from "../../api/users";
import { haptic } from "../../lib/telegram";
import { showToast } from "../../lib/toast";

// Shown when the app is opened via someone's personal «add me as a friend» deep-link (friend_<id>_<sig>).
// Peeks who's behind it (server-gated on the sig), then accepting makes you mutual friends instantly.
export function FriendInviteAccept({
  invite,
  onAccepted,
  onClose,
}: {
  invite: { inviterId: number; sig: string };
  onAccepted: (firstFriend: boolean) => void;
  onClose: () => void;
}) {
  const [inviter, setInviter] = useState<Friend | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    peekFriendLink(invite.inviterId, invite.sig).then((p) => {
      if (!alive) return;
      setInviter(p);
      setLoading(false);
      if (!p) onClose(); // a forged / stale / self link → just dismiss
    });
    return () => {
      alive = false;
    };
  }, [invite, onClose]);

  const accept = async () => {
    if (busy) return;
    setBusy(true);
    haptic("medium");
    const res = await acceptFriendLink(invite.inviterId, invite.sig);
    if (res && (res.added || res.friend)) {
      const name = res.friend?.name || inviter?.name || "";
      showToast(name ? `Теперь вы друзья с ${name}` : "Теперь вы друзья!", { tone: "good" });
      onAccepted(!!res.firstFriend);
    } else {
      showToast("Не удалось добавить в друзья", { tone: "muted" });
    }
    onClose();
  };

  if (loading || !inviter) return null; // nothing to show until we know who (or it's invalid → dismissed)

  return (
    <div className="fdisc-veil" onClick={onClose}>
      <div className="fdisc" role="dialog" aria-modal="true" aria-label="Заявка в друзья" onClick={(e) => e.stopPropagation()}>
        <span className="fdisc__kicker">друзья</span>
        <h3 className="fdisc__title">{(inviter.name || "кто-то").toLowerCase()} зовёт в друзья</h3>
        <p className="fdisc__body">
          Станете друзьями — будете видеть, что друг у друга в избранном. Скрыть отдельное событие можно в
          его карточке, всё сразу — в разделе «Друзья».
        </p>
        <div className="fdisc__actions">
          <button type="button" className="fdisc__ghost" onClick={onClose}>
            не сейчас
          </button>
          <button type="button" className="fdisc__cta" onClick={accept} disabled={busy}>
            принять
          </button>
        </div>
      </div>
    </div>
  );
}
