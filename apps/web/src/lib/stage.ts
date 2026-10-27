/**
 * Screen-mat stage colour (per device). Mirrors `services/metrology/mats.STAGE_COLOURS`: only the stage rectangle changes;
 * the marker ring always stays black on white. Dark suits white, grey and beige parts.
 */
"use client";

import { useSyncExternalStore } from "react";

export const STAGE_COLOURS = { light: "#FFFFFF", dark: "#303030" } as const;
export type StageTone = keyof typeof STAGE_COLOURS;
const STORAGE_SLOT = "partsmith.mat-stage.v1";
const EVENT = "partsmith:stage";

function read(): StageTone {
  try {
    return window.localStorage.getItem(STORAGE_SLOT) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function setStageTone(tone: StageTone): void {
  try {
    window.localStorage.setItem(STORAGE_SLOT, tone);
  } catch {
    /* storage blocked: still applies for this view */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useStageTone(): StageTone {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener(EVENT, cb);
      window.addEventListener("storage", cb);
      return () => {
        window.removeEventListener(EVENT, cb);
        window.removeEventListener("storage", cb);
      };
    },
    read,
    () => "light",
  );
}
