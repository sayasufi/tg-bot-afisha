import { useEffect, useRef, useState } from "react";

import { haptic } from "./telegram";

const THRESHOLD = 64; // px of resisted pull needed to arm a refresh
const MAX = 92;

// Pull-to-refresh for a scrollable element. Attach the returned `ref` to the
// scroll container; `pull` (0..MAX) and `armed` drive a hint, and onRefresh
// fires once the user releases past the threshold from the very top.
export function usePullToRefresh(onRefresh: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const pullRef = useRef(0);
  const [pull, setPull] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let startY = 0;
    let active = false;
    let armed = false;

    const reset = () => {
      pullRef.current = 0;
      setPull(0);
    };
    const onStart = (e: TouchEvent) => {
      active = el.scrollTop <= 0;
      armed = false;
      startY = e.touches[0].clientY;
    };
    const onMove = (e: TouchEvent) => {
      if (!active) return;
      if (el.scrollTop > 0) {
        active = false;
        reset();
        return;
      }
      const dy = e.touches[0].clientY - startY;
      if (dy <= 0) {
        reset();
        return;
      }
      const d = Math.min(dy * 0.5, MAX);
      pullRef.current = d;
      setPull(d);
      if (d >= THRESHOLD && !armed) {
        armed = true;
        haptic("light");
      } else if (d < THRESHOLD) {
        armed = false;
      }
      if (d > 4 && e.cancelable) e.preventDefault();
    };
    const onEnd = () => {
      if (!active) return;
      active = false;
      if (pullRef.current >= THRESHOLD) onRefresh();
      reset();
    };

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd);
    el.addEventListener("touchcancel", onEnd);
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", onEnd);
    };
  }, [onRefresh]);

  return { ref, pull, armed: pull >= THRESHOLD };
}
