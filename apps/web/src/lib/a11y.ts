import type * as React from "react";

/** Arrow-key navigation for custom role="radiogroup" containers: ←/↑ previous, →/↓ next, Home/End; selects on move. */
export function radioGroupKeys(e: React.KeyboardEvent<HTMLElement>): void {
  const keys = ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown", "Home", "End"];
  if (!keys.includes(e.key)) return;
  const radios = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="radio"]:not([disabled])'));
  const i = radios.indexOf(document.activeElement as HTMLElement);
  if (i < 0 || radios.length === 0) return;
  e.preventDefault();
  const n = radios.length;
  const next = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (i - 1 + n) % n : (i + 1) % n;
  radios[next]!.focus();
  radios[next]!.click();
}
