import { useEffect, useRef } from "react";

// Damped horizontal drag for the rail tracks. Native touch scroll moves content 1:1 with the
// finger; here the content tracks at `factor` (<1), so you move your finger farther for the
// same scroll — a calmer, slower rail. A light inertia on release keeps it gliding (not a
// dead stop). Vertical drags fall through untouched, so the page still scrolls normally.
export function useRailScroll<T extends HTMLElement = HTMLDivElement>(factor = 0.6) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let startX = 0;
    let startY = 0;
    let startLeft = 0;
    let lastT = 0;
    let vel = 0; // scroll px per ms
    let axis: "" | "h" | "v" = "";
    let raf = 0;

    const stopInertia = () => {
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };
    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      stopInertia();
      const t = e.touches[0];
      startX = t.clientX;
      startY = t.clientY;
      startLeft = el.scrollLeft;
      lastT = e.timeStamp;
      vel = 0;
      axis = "";
    };
    const onMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      const t = e.touches[0];
      const dx = t.clientX - startX;
      const dy = t.clientY - startY;
      if (!axis) {
        if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return; // too small to decide
        axis = Math.abs(dx) > Math.abs(dy) ? "h" : "v";
      }
      if (axis !== "h") return; // vertical → let the page scroll
      e.preventDefault();
      const prev = el.scrollLeft;
      el.scrollLeft = startLeft - dx * factor;
      const dt = e.timeStamp - lastT || 16;
      vel = (el.scrollLeft - prev) / dt;
      lastT = e.timeStamp;
    };
    const onEnd = () => {
      if (axis === "h" && Math.abs(vel) > 0.02) {
        let v = vel;
        let last = 0;
        const step = (now: number) => {
          if (!last) last = now;
          const dt = now - last;
          last = now;
          el.scrollLeft += v * dt;
          v *= Math.pow(0.95, dt / 16); // friction
          raf = Math.abs(v) > 0.02 ? requestAnimationFrame(step) : 0;
        };
        raf = requestAnimationFrame(step);
      }
      axis = "";
    };

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd, { passive: true });
    el.addEventListener("touchcancel", onEnd, { passive: true });
    return () => {
      stopInertia();
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", onEnd);
    };
  }, [factor]);
  return ref;
}
