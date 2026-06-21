import { type ReactNode, useEffect, useState } from "react";

import {
  createFriendLink,
  findFriend,
  type FoundFriend,
  type Friend,
  type FriendsState,
  manageFriends,
} from "../../api/users";
import { IconClose } from "../../lib/icons";
import { haptic, shareEvent } from "../../lib/telegram";
import { showToast } from "../../lib/toast";
import { safeHttpUrl } from "../../lib/url";
import { FriendDisclosure } from "./FriendDisclosure";

// One person row: avatar · name/@handle (taps to open their profile, if onOpen) · trailing action(s).
// Module-level so it isn't re-created (rows re-mounted, avatars flickering) on every parent render.
function FriendRow({ f, onOpen, children }: { f: Friend; onOpen?: (f: Friend) => void; children: ReactNode }) {
  const av = safeHttpUrl(f.photo_url);
  const initial = (f.name || "?").slice(0, 1).toUpperCase();
  const inner = (
    <>
      <span className="profile__friend-av" style={av ? { backgroundImage: `url("${av}")` } : undefined}>
        {av ? "" : initial}
      </span>
      <span className="profile__friend-id">
        <span className="profile__friend-name">{f.name || "Друг"}</span>
        {f.username && <span className="profile__friend-handle">@{f.username}</span>}
      </span>
    </>
  );
  return (
    <div className="profile__friend">
      {onOpen ? (
        <button
          type="button"
          className="profile__friend-tap"
          aria-label={`Профиль ${f.name || "друга"}`}
          onClick={() => onOpen(f)}
        >
          {inner}
        </button>
      ) : (
        <span className="profile__friend-main">{inner}</span>
      )}
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
  isSearchable,
  onToggleSearchable,
  onRequestsChange,
  onOpenFriend,
  onClose,
}: {
  friendsPrivate: boolean;
  onToggleFriendsPrivate: (on: boolean) => void;
  isSearchable: boolean;
  onToggleSearchable: (on: boolean) => void;
  onRequestsChange?: (n: number) => void;
  onOpenFriend?: (f: Friend) => void;
  onClose: () => void;
}) {
  const [friends, setFriends] = useState<Friend[]>([]);
  const [requests, setRequests] = useState<Friend[]>([]);
  const [disclose, setDisclose] = useState(false);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [found, setFound] = useState<FoundFriend | null>(null); // null = no search; {found:false} = miss
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
  const inviteFriend = async () => {
    haptic("light");
    const link = await createFriendLink();
    if (!link) {
      showToast("Не удалось создать ссылку", { tone: "muted" });
      return;
    }
    shareEvent({ title: "Добавь меня в Окрест 👋", text: "будем видеть, что друг у друга в избранном", url: link });
  };
  const handle = () => query.trim().replace(/^@+/, "");
  const doSearch = async () => {
    const u = handle();
    if (!u || searching) return;
    haptic("light");
    setSearching(true);
    const res = await findFriend(u, false);
    setSearching(false);
    if (!res) {
      showToast("Слишком много поисков или ошибка", { tone: "muted" });
      return;
    }
    setFound(res);
  };
  const sendRequest = async () => {
    if (!found?.user) return;
    haptic("light");
    const res = await findFriend(handle(), true);
    if (!res) {
      showToast("Не удалось отправить", { tone: "muted" });
      return;
    }
    setFound(res);
    if (res.status === "accepted") {
      showToast("Теперь вы друзья!", { tone: "good" });
      void manageFriends().then(apply); // the reciprocal upgrade added a friend
    } else if (res.status === "pending") {
      showToast("Заявка отправлена", { tone: "good" });
    }
  };
  const acceptFound = (f: Friend) => {
    accept(f.id); // reuse the «Заявки» accept (optimistic + refresh + first-friend disclosure)
    setFound((cur) => (cur ? { ...cur, relation: "friends" } : cur));
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
        <button type="button" className="friends__invite" onClick={inviteFriend}>
          пригласить друга в окрест →
        </button>

        <div className="friends__search">
          <input
            className="friends__search-input"
            type="text"
            inputMode="text"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder="найти по @username"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void doSearch();
            }}
            aria-label="Найти друга по @username"
          />
          <button
            type="button"
            className="friends__search-go"
            onClick={() => void doSearch()}
            disabled={searching || !handle()}
          >
            {searching ? "…" : "найти"}
          </button>
        </div>
        {found &&
          (found.found && found.user ? (
            <div className="profile__friends">
              <FriendRow f={found.user} onOpen={found.relation === "friends" ? onOpenFriend : undefined}>
                {found.relation === "friends" ? (
                  <span className="friends__found-state">вы друзья</span>
                ) : found.relation === "pending_out" ? (
                  <span className="friends__found-state">заявка отправлена</span>
                ) : found.relation === "pending_in" ? (
                  <button type="button" className="profile__req-accept" onClick={() => acceptFound(found.user!)}>
                    принять
                  </button>
                ) : (
                  <button type="button" className="profile__req-accept" onClick={() => void sendRequest()}>
                    добавить
                  </button>
                )}
              </FriendRow>
            </div>
          ) : (
            <p className="profile__friends-empty">Никого не нашли по этому нику.</p>
          ))}
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
              <FriendRow key={f.id} f={f} onOpen={onOpenFriend}>
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

        <button
          type="button"
          className={`profile__switch${isSearchable ? " profile__switch--on" : ""}`}
          role="switch"
          aria-checked={isSearchable}
          onClick={() => onToggleSearchable(!isSearchable)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Находить меня по @username</span>
            <span className="profile__switch-sub">По умолчанию выключено. Включи — и друзья смогут найти тебя по нику и отправить заявку</span>
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
