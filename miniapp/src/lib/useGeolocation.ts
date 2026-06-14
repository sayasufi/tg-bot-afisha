import { useCallback, useEffect, useRef, useState } from "react";

import { saveUserLocation } from "../api/client";
import { haptic } from "./telegram";
import { isLocationGranted, openLocationSettings, watchLocation } from "./telegramLocation";

// Live user position + compass heading, plus a one-tap "locate" that recentres
// the map. Extracted from App so the component stays about layout, not GPS.
export function useGeolocation() {
  const [locating, setLocating] = useState(false);
  const [locateNonce, setLocateNonce] = useState(0);
  const [userPos, setUserPos] = useState<[number, number] | null>(null);
  const [heading, setHeading] = useState<number | null>(null);
  const stopWatch = useRef<(() => void) | null>(null);
  const wantCenter = useRef(false);
  const savedLoc = useRef(false);
  const orientHandler = useRef<((e: any) => void) | null>(null);
  const lastHeading = useRef<number | null>(null);

  // Live position watch. Prefers Telegram's LocationManager — the grant is
  // stored per-bot, so the user is asked ONCE and never re-prompted on later
  // opens (navigator.geolocation re-prompts every open inside the WebView).
  const startWatch = useCallback(() => {
    if (stopWatch.current) return;
    stopWatch.current = watchLocation(
      (c) => {
        setUserPos([c.latitude, c.longitude]);
        // Save the home city from the first fix only (reverse-geocoded server-side).
        if (!savedLoc.current) {
          savedLoc.current = true;
          void saveUserLocation(c.latitude, c.longitude);
        }
      },
      {
        onDenied: () => {
          setLocating(false);
          openLocationSettings(); // offer Telegram's settings if previously denied
        },
      },
    );
  }, []);

  // Start tracking automatically on open when access was already granted, so the
  // live position shows without a tap.
  useEffect(() => {
    let cancelled = false;
    isLocationGranted().then((ok) => {
      if (ok && !cancelled) startWatch();
    });
    return () => {
      cancelled = true;
    };
  }, [startWatch]);

  // Compass heading (where the phone points). iOS needs an explicit permission
  // grant triggered from a user gesture, so we kick this off on the locate tap.
  const startOrientation = async () => {
    if (orientHandler.current) return;
    const DOE: any = (window as any).DeviceOrientationEvent;
    if (!DOE) return;
    try {
      if (typeof DOE.requestPermission === "function") {
        const res = await DOE.requestPermission();
        if (res !== "granted") return;
      }
    } catch {
      return;
    }
    const handler = (e: any) => {
      let h: number | null = null;
      if (typeof e.webkitCompassHeading === "number") h = e.webkitCompassHeading; // iOS: clockwise from north
      else if (e.absolute && e.alpha != null) h = (360 - e.alpha) % 360;
      if (h == null || Number.isNaN(h)) return;
      h = Math.round(h);
      // Throttle: only re-render when the heading moved meaningfully (>=2°).
      const prev = lastHeading.current;
      if (prev != null) {
        const delta = Math.min(Math.abs(h - prev), 360 - Math.abs(h - prev));
        if (delta < 2) return;
      }
      lastHeading.current = h;
      setHeading(h);
    };
    orientHandler.current = handler;
    const evt = "ondeviceorientationabsolute" in window ? "deviceorientationabsolute" : "deviceorientation";
    window.addEventListener(evt, handler, true);
  };

  useEffect(() => {
    return () => {
      stopWatch.current?.();
      if (orientHandler.current) {
        window.removeEventListener("deviceorientationabsolute", orientHandler.current, true);
        window.removeEventListener("deviceorientation", orientHandler.current, true);
      }
    };
  }, []);

  // When the first fix lands after a locate tap, recentre on the user.
  useEffect(() => {
    if (userPos && wantCenter.current) {
      wantCenter.current = false;
      setLocating(false);
      setLocateNonce((n) => n + 1);
    }
  }, [userPos]);

  // Centre the map on the user (and start showing the live position + heading).
  // It never replaces the events on the map — all of them stay put.
  const onLocate = useCallback(() => {
    haptic("medium");
    void startOrientation();
    if (userPos) {
      setLocateNonce((n) => n + 1);
    } else {
      wantCenter.current = true;
      setLocating(true);
      startWatch();
    }
    // startOrientation is closure-stable (refs + setters only).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userPos, startWatch]);

  return { userPos, heading, locating, locateNonce, onLocate };
}
