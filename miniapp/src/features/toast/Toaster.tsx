import { useEffect, useState } from "react";

import { IconBell, IconHeart, IconShare } from "../../lib/icons";
import { subscribeToast, type ToastIcon, type ToastMsg } from "../../lib/toast";

function glyph(icon?: ToastIcon) {
  if (icon === "heart") return <IconHeart filled size={15} />;
  if (icon === "bell") return <IconBell filled size={15} />;
  if (icon === "share") return <IconShare size={15} />;
  return null;
}

// Renders the current toast: slides up, holds ~1.8s, slides out. `key={id}` re-mounts on
// each new message so the enter animation replays even for back-to-back taps.
export function Toaster() {
  const [toast, setToast] = useState<ToastMsg | null>(null);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => subscribeToast((t) => {
    setToast(t);
    setLeaving(false);
  }), []);

  useEffect(() => {
    if (!toast || leaving) return;
    const t = setTimeout(() => setLeaving(true), 1800);
    return () => clearTimeout(t);
  }, [toast, leaving]);

  useEffect(() => {
    if (!leaving) return;
    const t = setTimeout(() => {
      setToast(null);
      setLeaving(false);
    }, 220);
    return () => clearTimeout(t);
  }, [leaving]);

  if (!toast) return null;
  return (
    <div className="toast-wrap" aria-live="polite">
      <div
        key={toast.id}
        className={`toast toast--${toast.tone}${leaving ? " toast--leaving" : ""}`}
        role="status"
      >
        {toast.icon && (
          <span className="toast__glyph" aria-hidden="true">
            {glyph(toast.icon)}
          </span>
        )}
        <span className="toast__text">{toast.text}</span>
      </div>
    </div>
  );
}
