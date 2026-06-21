import { type ReactNode, useEffect, useState } from "react";

import { manageFriends, type Friend, type FriendsState } from "../../api/users";
import { IconClose } from "../../lib/icons";
import { haptic } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";
import { FriendDisclosure } from "./FriendDisclosure";

// One person row: avatar · name/@handle · trailing action(s). Module-level so it isn't re-created
// (and the rows re-mounted, flickering avatars) on every parent render.
function FriendRow({ f, children }: { f: Friend; children: ReactNode }) {
  const av = safeHttpUrl(f.photo_url);
  const initial = (f.name || "?").slice(0, 1).toUpperCase();
  return (
    <div className="profile__friend">
      <span className="profile__friend-av" style={av ? { backgroundImage: `url("${av}")` } : undefined}>
        {av ? "" : initial}
      </span>
      <span className="profile__friend-id">
        <span className="profile__friend-name">{f.name || "Друг"}</span>
        {f.username && <span className="profile__friend-handle">@{f.username}</span>}
      </span>
      {children}
    </div>
  );
}

// «Друзья» — its own screen. Incoming requests (accept/decline) + confirmed friends (unfriend) + the
// privacy kill-switch. A friend appears here once BOTH sides agreed (you accepted a request, or you
// each invited the other). onRequestsChange keeps the menu badge in sync.
export function FriendsPanel({
  friendsPrivate,
  onToggleFriendsPrivate,
  onRequestsChange,
  onClose,
}: {
  friendsPrivate: boolean;
  onToggleFriendsPrivate: (on: boolean) => void;
  onRequestsChange?: (n: number) => void;
  onClose: () => void;
}) {
  const [friends, setFriends] = useState<Friend[]>([]);
  const [requests, setRequests] = useState<Friend[]>([]);
  const [disclose, setDisclose] = useState(false);
  const apply = (s: FriendsState | null) => {
    if (!s) return;
    setFriends(s.friends);
    setRequests(s.requests);
    onRequestsChange?.(s.requests.length);
  };
  useEffect(() => {
    let alive = true;
    manageFriends().then((s) => {
      if (alive) apply(s);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const accept = (id: number) => {
    haptic("light");
    setRequests((rs) => rs.filter((r) => r.id !== id)); // optimistic
    onRequestsChange?.(requests.length - 1);
    void manageFriends("accept", id).then((s) => {
      apply(s);
      if (s?.firstFriend) {
        try {
          if (localStorage.getItem("okrest_friend_disclosed") !== "1") {
            localStorage.setItem("okrest_friend_disclosed", "1");
            setDisclose(true);
          }
        } catch {
          /* ignore */
        }
      }
    });
  };
  const decline = (id: number) => {
    setRequests((rs) => rs.filter((r) => r.id !== id)); // optimistic
    onRequestsChange?.(requests.length - 1);
    void manageFriends("decline", id).then(apply);
  };
  const remove = (id: number) => {
    setFriends((fs) => fs.filter((f) => f.id !== id)); // optimistic
    void manageFriends("remove", id).then(apply);
  };

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>друзья</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll">
        {requests.length > 0 && (
          <>
            <div className="recs__section">Заявки</div>
            <div className="profile__friends">
              {requests.map((f) => (
                <FriendRow key={f.id} f={f}>
                  <span className="profile__req-actions">
                    <button type="button" className="profile__req-accept" onClick={() => accept(f.id)}>
                      принять
                    </button>
                    <button
                      type="button"
                      className="profile__friend-x"
                      aria-label={`Отклонить ${f.name || "заявку"}`}
                      onClick={() => decline(f.id)}
                    >
                      ×
                    </button>
                  </span>
                </FriendRow>
              ))}
            </div>
          </>
        )}

        <div className="recs__section">Друзья</div>
        {friends.length > 0 ? (
          <div className="profile__friends">
            {friends.map((f) => (
              <FriendRow key={f.id} f={f}>
                <button
                  type="button"
                  className="profile__friend-x"
                  aria-label={`Убрать ${f.name || "друга"} из друзей`}
                  onClick={() => remove(f.id)}
                >
                  ×
                </button>
              </FriendRow>
            ))}
          </div>
        ) : (
          <p className="profile__friends-empty">
            Поделись событием через «Пойдём?» — кто примет приглашение, сразу станет другом. После этого вы
            будете видеть, что друг у друга в избранном.
          </p>
        )}

        <button
          type="button"
          className={`profile__switch${friendsPrivate ? " profile__switch--on" : ""}`}
          role="switch"
          aria-checked={friendsPrivate}
          onClick={() => onToggleFriendsPrivate(!friendsPrivate)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Скрыть от друзей</span>
            <span className="profile__switch-sub">Друзья не увидят, что ты сохраняешь. Отдельное событие можно скрыть в его карточке</span>
          </span>
          <span className="profile__switch-track" aria-hidden="true">
            <span className="profile__switch-knob" />
          </span>
        </button>
      </div>
      {disclose && <FriendDisclosure onClose={() => setDisclose(false)} />}
    </div>
  );
}
