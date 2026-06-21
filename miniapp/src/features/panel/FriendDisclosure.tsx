// One-time disclosure shown the moment an account gets its VERY FIRST friend (when it confirms an
// incoming request) — so nobody's saves become visible to a friend by surprise. Gated once (localStorage).
export function FriendDisclosure({ onClose, onOpenProfile }: { onClose: () => void; onOpenProfile?: () => void }) {
  return (
    <div className="fdisc-veil" onClick={onClose}>
      <div className="fdisc" role="dialog" aria-modal="true" aria-label="Друзья" onClick={(e) => e.stopPropagation()}>
        <span className="fdisc__kicker">друзья</span>
        <h3 className="fdisc__title">теперь вы друзья</h3>
        <p className="fdisc__body">
          Друзья видят, что ты сохраняешь — а ты видишь их. Любое событие можно скрыть прямо в его
          карточке, а всё сразу — в разделе «Друзья».
        </p>
        <div className="fdisc__actions">
          {onOpenProfile && (
            <button type="button" className="fdisc__ghost" onClick={onOpenProfile}>
              настройки
            </button>
          )}
          <button type="button" className="fdisc__cta" onClick={onClose}>
            понятно
          </button>
        </div>
      </div>
    </div>
  );
}
