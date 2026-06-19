import { useEffect, useState } from "react";

// A thin top alert shown while the device is offline — so a failed map/feed load reads as
// "no network" rather than "nothing here". Self-contained: tracks the browser online state.
export function OfflineBanner() {
  const [offline, setOffline] = useState(() => typeof navigator !== "undefined" && navigator.onLine === false);
  useEffect(() => {
    const sync = () => setOffline(!navigator.onLine);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);
  if (!offline) return null;
  return (
    <div className="offline" role="status" aria-live="polite">
      нет соединения
    </div>
  );
}
