import { type ReactNode, useEffect, useState } from "react";

import type { EventItem } from "../../api/types";
import {
  createFriendLink,
  fetchFriendsActivity,
  findFriend,
  type FoundFriend,
  type Friend,
  type FriendActivity,
  type FriendsState,
  manageFriends,
} from "../../api/users";
import { IconClose } from "../../lib/icons";
import { haptic, shareEvent } from "../../lib/telegram";
import { showToast } from "../../lib/toast";
import { safeHttpUrl } from "../../lib/url";
import { FriendDisclosure } from "./FriendDisclosure";

// Compact «N сохранений» with Russian plural agreement.
function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

// Coarse «когда» label for the activity feed (the API timestamps are minute-grained at best).
function timeAgo(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const sec = Math.max(0, (Date.now() - t) / 1000);
  if (sec < 90) return "только что";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} мин назад`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const d = Math.round(hr / 24);
  if (d === 1) return "вчера";
  if (d < 7) return `${d} дн назад`;
  return `${Math.round(d / 7)} нед назад`;
}

function Avatar({ f }: { f: Friend }) {
  const av = safeHttpUrl(f.photo_url);
  return (
    <span className="profile__friend-av" style={av ? { backgroundImage: `url("${av}")` } : undefined}>
      {av ? "" : (f.name || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

// One person row: avatar · name/@handle (taps to open their profile, if onOpen) · trailing action(s).
// Module-level so it isn't re-created (rows re-mounted, avatars flickering) on every parent render.
function FriendRow({ f, onOpen, children }: { f: Friend; onOpen?: (f: Friend) => void; children: ReactNode }) {
  const inner = (
    <>
      <Avatar f={f} />
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

// One «Активность друзей» row — who saved which event, when. Taps straight into the event sheet.
function ActivityRow({ a, onOpen }: { a: FriendActivity; onOpen: (e: EventItem) => void }) {
  const who = a.friend.username ? `@${a.friend.username}` : a.friend.name || "друг";
  return (
    <button type="button" className="friends__act" onClick={() => onOpen(a.event)}>
      <Avatar f={a.friend} />
      <span className="friends__act-body">
        <span className="friends__act-text">
          <b>{who}</b> сохранил <span className="friends__act-ev">«{a.event.title}»</span>
        </span>
        <span className="friends__act-time">{timeAgo(a.at)}</span>
      </span>
    </button>
  );
}

// «Друзья» — its own screen. Two mechanics: the friends' recent-saves FEED on top (tap → that event), and
// the friend LIST below (tap → their profile, with a «N сохранений» signal). Plus the ways to grow the
// graph: an invite link, @username search, and incoming requests. The «скрыть от друзей» kill-switch now
// lives in the Profile screen. onFriendsChange keeps the menu badge (friend count) in sync.
export function FriendsPanel({
  onFriendsChange,
  onOpenFriend,
  onOpenEvent,
  onClose,
}: {
  onFriendsChange?: (n: number) => void;
  onOpenFriend?: (f: Friend) => void;
  onOpenEvent: (e: EventItem) => void;
  onClose: () => void;
}) {
  const [friends, setFriends] = useState<Friend[]>([]);
  const [requests, setRequests] = useState<Friend[]>([]);
  const [activity, setActivity] = useState<FriendActivity[]>([]);
  const [disclose, setDisclose] = useState(false);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [found, setFound] = useState<FoundFriend | null>(null); // null = no search; {found:false} = miss
  const apply = (s: FriendsState | null) => {
    if (!s) return;
    setFriends(s.friends);
    setRequests(s.requests);
    onFriendsChange?.(s.friends.length);
  };
  useEffect(() => {
    let alive = true;
    manageFriends().then((s) => {
      if (alive) apply(s);
    });
    fetchFriendsActivity().then((a) => {
      if (alive && a) setActivity(a);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const accept = (id: number) => {
    haptic("light");
    setRequests((rs) => rs.filter((r) => r.id !== id)); // optimistic
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

        {activity.length > 0 && (
          <>
            <div className="recs__section">Активность друзей</div>
            <div className="friends__feed">
              {activity.map((a, i) => (
                <ActivityRow key={`${a.friend.id}-${a.event.event_id}-${i}`} a={a} onOpen={onOpenEvent} />
              ))}
            </div>
          </>
        )}

        <div className="recs__section">Друзья{friends.length > 0 ? ` · ${friends.length}` : ""}</div>
        {friends.length > 0 ? (
          <div className="profile__friends">
            {friends.map((f) => (
              <FriendRow key={f.id} f={f} onOpen={onOpenFriend}>
                {f.saves ? (
                  <span className="friends__saves">
                    <b>{f.saves}</b> {plural(f.saves, "сохранение", "сохранения", "сохранений")}
                  </span>
                ) : null}
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
      </div>
      {disclose && <FriendDisclosure onClose={() => setDisclose(false)} />}
    </div>
  );
}
