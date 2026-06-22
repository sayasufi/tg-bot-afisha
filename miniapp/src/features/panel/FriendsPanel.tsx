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
import { categoryMeta } from "../../lib/categories";
import { IconClose, IconSearch } from "../../lib/icons";
import { haptic, shareEvent } from "../../lib/telegram";
import { showToast } from "../../lib/toast";
import { safeHttpUrl } from "../../lib/url";
import { FriendDisclosure } from "./FriendDisclosure";

// «любит концерты, театр» from a friend's 1-2 top category slugs — a lighter, more human signal than a
// bare save count. Empty when they have no visible saves (new / private friend).
function tasteLabel(cats?: string[]): string {
  if (!cats || !cats.length) return "";
  return `любит ${cats.map((c) => categoryMeta(c).label.toLowerCase()).join(", ")}`;
}

// In the feed, lead with just the MAIN title — drop a trailing subtitle after the first «. » / « — » / « · »
// (event titles are «Main. Subtitle»). The full title still shows in the event card. Guarded to ≥6 chars so
// it never cuts to a stub; the CSS still clamps to one line as a backstop.
function shortTitle(t: string): string {
  const s = (t || "").trim();
  const m = s.match(/^(.{6,}?)(?:\.\s|\s[—–·|]\s)/);
  return (m ? m[1] : s).trim();
}

const ACT_PREVIEW = 8; // chronicle rows shown before «вся хроника» (the API already caps the feed at 24)
const FR_PREVIEW = 12; // friend rows shown before «показать всех»

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
      {av ? "" : (f.name || f.username || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

// One person row: avatar · name + (taste/@handle) (taps to open their profile, if onOpen) · trailing
// action(s). `subtitle` overrides the default @handle line (the friend list passes the taste line).
// Module-level so it isn't re-created (rows re-mounted, avatars flickering) on every parent render.
function FriendRow({
  f,
  onOpen,
  subtitle,
  children,
}: {
  f: Friend;
  onOpen?: (f: Friend) => void;
  subtitle?: string;
  children?: ReactNode;
}) {
  const inner = (
    <>
      <Avatar f={f} />
      <span className="profile__friend-id">
        <span className="profile__friend-name">{f.name || (f.username ? `@${f.username}` : "Друг")}</span>
        {subtitle !== undefined ? (
          subtitle ? (
            <span className="profile__friend-sub">{subtitle}</span>
          ) : null
        ) : (
          f.username && <span className="profile__friend-handle">@{f.username}</span>
        )}
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

// One «Хроника друзей» row — friend avatar leads, then the event TITLE (primary) over a quiet «кто · когда»
// byline, with the event poster on the right. A chronicle of friends' finds. Taps into the sheet.
function ActivityRow({ a, onOpen }: { a: FriendActivity; onOpen: (e: EventItem) => void }) {
  const who = a.friend.name || (a.friend.username ? `@${a.friend.username}` : "друг");
  const cover = safeHttpUrl(a.event.primary_image_url);
  return (
    <button type="button" className="friends__act" onClick={() => onOpen(a.event)}>
      <Avatar f={a.friend} />
      <span className="friends__act-body">
        <span className="friends__act-ev">{shortTitle(a.event.title)}</span>
        <span className="friends__act-meta">
          <span className="friends__act-who">{who}</span> сохранил · {timeAgo(a.at)}
        </span>
      </span>
      <span
        className={`friends__act-cover${cover ? "" : " friends__act-cover--ph"}`}
        style={cover ? { backgroundImage: `url("${cover}")` } : undefined}
        aria-hidden="true"
      />
    </button>
  );
}

// «Друзья» — its own screen. Two mechanics: the friends' recent-saves FEED right under the header (tap →
// that event), and the friend LIST below (tap → their profile, with a «любит …» taste line). @username
// search is tucked behind a header icon; the invite link sits quietly at the bottom. The «скрыть от
// друзей» kill-switch now lives in Profile. onFriendsChange keeps the menu badge (friend count) in sync.
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
  // Scale: the feed/list can grow, so cap each to a scannable preview with a «показать всё» expander —
  // the chronicle never buries the friend list, and a big roster doesn't make an endless scroll.
  const [activityFull, setActivityFull] = useState(false);
  const [friendsFull, setFriendsFull] = useState(false);
  const [tab, setTab] = useState<"activity" | "friends">("activity"); // two segments so the list isn't buried under the feed
  const [disclose, setDisclose] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
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
        <span className="panelview__head-actions">
          <button
            type="button"
            className={`panelview__icon${searchOpen ? " panelview__icon--on" : ""}`}
            aria-label="Найти друга по @username"
            aria-pressed={searchOpen}
            onClick={() => setSearchOpen((o) => !o)}
          >
            <IconSearch size={18} />
          </button>
          <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
            <IconClose size={18} />
          </button>
        </span>
      </header>
      <div className="panelview__scroll">
        {searchOpen && (
          <>
            <div className="friends__search">
              <input
                className="friends__search-input"
                type="text"
                inputMode="text"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
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
          </>
        )}

        <div className="friends__tabs" role="tablist" aria-label="Друзья">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "activity"}
            className={`friends__tab${tab === "activity" ? " friends__tab--on" : ""}`}
            onClick={() => setTab("activity")}
          >
            Хроника
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "friends"}
            className={`friends__tab${tab === "friends" ? " friends__tab--on" : ""}`}
            onClick={() => setTab("friends")}
          >
            Друзья
            {requests.length > 0 && <span className="friends__tab-badge">{requests.length}</span>}
          </button>
        </div>

        {tab === "activity" ? (
          activity.length > 0 ? (
            <>
              <div className="friends__feed">
                {(activityFull ? activity : activity.slice(0, ACT_PREVIEW)).map((a, i) => (
                  <ActivityRow key={`${a.friend.id}-${a.event.event_id}-${i}`} a={a} onOpen={onOpenEvent} />
                ))}
              </div>
              {!activityFull && activity.length > ACT_PREVIEW && (
                <button type="button" className="friends__more" onClick={() => setActivityFull(true)}>
                  вся хроника · ещё {activity.length - ACT_PREVIEW} →
                </button>
              )}
            </>
          ) : (
            <p className="profile__friends-empty">
              {friends.length === 0
                ? "Пока нет друзей. Добавь их во вкладке «Друзья» — и тут появится, что они сохраняют."
                : "Пока тихо — здесь появится, что сохраняют твои друзья."}
            </p>
          )
        ) : (
          <>
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
            {friends.length > 0 ? (
              <>
                <div className="profile__friends">
                  {(friendsFull ? friends : friends.slice(0, FR_PREVIEW)).map((f) => (
                    <FriendRow
                      key={f.id}
                      f={f}
                      onOpen={onOpenFriend}
                      subtitle={tasteLabel(f.top_cats) || (f.username ? `@${f.username}` : "")}
                    >
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
                {!friendsFull && friends.length > FR_PREVIEW && (
                  <button type="button" className="friends__more" onClick={() => setFriendsFull(true)}>
                    показать всех · {friends.length} →
                  </button>
                )}
              </>
            ) : (
              <p className="profile__friends-empty">
                Поделись событием через «Пойдём?» — кто примет приглашение, сразу станет другом. После этого
                вы будете видеть, что друг у друга в избранном.
              </p>
            )}

            <button type="button" className="friends__invite" onClick={inviteFriend}>
              <span className="friends__invite-plus" aria-hidden="true">+</span>
              пригласить друга
            </button>
          </>
        )}
      </div>
      {disclose && <FriendDisclosure onClose={() => setDisclose(false)} />}
    </div>
  );
}
