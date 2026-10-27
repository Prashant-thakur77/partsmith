/** Admin token for write actions (publish, Factory). Stored per device; sent as a Bearer token on API calls. */
const ADMIN_KEY = "partsmith.admin-token";
export const ADMIN_EVENT = "partsmith:admin";

export function adminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ADMIN_KEY);
  } catch {
    return null;
  }
}

export function setAdminToken(v: string | null): void {
  try {
    if (v) window.localStorage.setItem(ADMIN_KEY, v);
    else window.localStorage.removeItem(ADMIN_KEY);
  } catch {
    /* storage blocked */
  }
  window.dispatchEvent(new Event(ADMIN_EVENT));
}
