/**
 * Per-device screen calibration (ID-1 card, ISO/IEC 7810: 85.60 × 53.98 mm).
 * Stored in localStorage as CSS pixels per millimetre together with the devicePixelRatio and screen size it was measured at,
 * so a browser-zoom or display change is detected and the user is asked to recheck.
 */
"use client";

import { useSyncExternalStore } from "react";

export const CARD_W_MM = 85.6;
export const CARD_H_MM = 53.98;
export const CARD_ASPECT = CARD_W_MM / CARD_H_MM;
const KEY = "partsmith.screen-calibration.v1";
const EVENT = "partsmith:calibration";

export type ScreenCalibration = {
  px_per_mm: number;
  dpr: number;
  screen_w: number;
  screen_h: number;
  card_w_px: number;
  card_h_px: number;
  calibrated_at: number;
};

function read(): ScreenCalibration | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<ScreenCalibration>;
    if (typeof v.px_per_mm !== "number" || !(v.px_per_mm > 0)) return null;
    return v as ScreenCalibration;
  } catch {
    return null;
  }
}

let cache: { raw: string | null; value: ScreenCalibration | null } = { raw: null, value: null };

function snapshot(): ScreenCalibration | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (raw !== cache.raw) cache = { raw, value: read() };
  return cache.value;
}

function subscribe(cb: () => void): () => void {
  window.addEventListener("storage", cb);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(EVENT, cb);
  };
}

export function saveCalibration(cardWidthPx: number): ScreenCalibration {
  const cal: ScreenCalibration = {
    px_per_mm: cardWidthPx / CARD_W_MM,
    dpr: window.devicePixelRatio || 1,
    screen_w: window.screen.width,
    screen_h: window.screen.height,
    card_w_px: cardWidthPx,
    card_h_px: cardWidthPx / CARD_ASPECT,
    calibrated_at: Date.now(),
  };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(cal));
  } catch {
    /* storage blocked: the value still applies for this page view */
  }
  window.dispatchEvent(new Event(EVENT));
  return cal;
}

export function clearCalibration(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(EVENT));
}

/** Why a stored calibration may no longer be valid on this display (null when it still matches). */
export function calibrationDrift(cal: ScreenCalibration): string | null {
  const dpr = window.devicePixelRatio || 1;
  if (Math.abs(dpr - cal.dpr) > 0.01) {
    return `Browser zoom or display scaling changed (device pixel ratio ${cal.dpr.toFixed(2)} → ${dpr.toFixed(2)}).`;
  }
  if (window.screen.width !== cal.screen_w || window.screen.height !== cal.screen_h) {
    return `This looks like a different display (${cal.screen_w}×${cal.screen_h} → ${window.screen.width}×${window.screen.height} px).`;
  }
  return null;
}

export function useCalibration(): { calibration: ScreenCalibration | null; ready: boolean } {
  const calibration = useSyncExternalStore(subscribe, snapshot, () => null);
  const ready = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  return { calibration, ready };
}

/** Re-render when devicePixelRatio or the window size changes (zoom, display move). */
export function useDisplayKey(): string {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener("resize", cb);
      return () => window.removeEventListener("resize", cb);
    },
    () => `${window.devicePixelRatio}|${window.screen.width}x${window.screen.height}`,
    () => "ssr",
  );
}
