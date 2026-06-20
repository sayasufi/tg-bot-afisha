import { useEffect, type RefObject } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

// getClientRects() (not offsetParent) so position:fixed modals — whose offsetParent is null even
// when visible — aren't wrongly treated as hidden.
const isVisible = (el: HTMLElement) => el.getClientRects().length > 0;

/**
 * Keyboard focus trap for an open modal dialog. On activation it moves focus into the dialog,
 * keeps Tab / Shift+Tab cycling within its focusable elements (wrapping at both ends, and pulling
 * focus back if it ever escapes), and restores focus to the opener when the dialog closes. Pairs
 * with role="dialog" + aria-modal so keyboard and screen-reader users can't wander into the inert
 * page behind the overlay. The container needs tabIndex={-1} so it can hold focus itself. No-op
 * while `active` is false (e.g. a CSS-animated sheet that stays mounted when closed).
 */
export function useFocusTrap(
  ref: RefObject<HTMLElement>,
  active: boolean,
  initialFocus?: RefObject<HTMLElement>,
): void {
  useEffect(() => {
    const node = ref.current;
    if (!active || !node) return;
    const opener = document.activeElement as HTMLElement | null;
    const list = () => Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(isVisible);

    // Default: focus the container (announces the dialog without highlighting a control). A caller
    // can name a better target — e.g. a search input.
    const wanted = initialFocus?.current;
    (wanted && isVisible(wanted) ? wanted : node).focus({ preventScroll: true });

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const els = list();
      if (!els.length) {
        e.preventDefault();
        node.focus({ preventScroll: true });
        return;
      }
      const first = els[0];
      const last = els[els.length - 1];
      const a = document.activeElement;
      if (!node.contains(a)) {
        e.preventDefault();
        first.focus({ preventScroll: true });
      } else if (e.shiftKey && a === first) {
        e.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!e.shiftKey && a === last) {
        e.preventDefault();
        first.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      // Return focus to whatever opened the dialog, if it's still in the document.
      if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
    };
  }, [ref, active, initialFocus]);
}
