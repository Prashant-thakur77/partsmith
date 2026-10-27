"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import * as React from "react";
import { ADMIN_EVENT, adminToken, setAdminToken } from "@/lib/admin";
import { api } from "@/lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

function useHasToken(): boolean {
  return React.useSyncExternalStore(
    (cb) => {
      window.addEventListener(ADMIN_EVENT, cb);
      return () => window.removeEventListener(ADMIN_EVENT, cb);
    },
    () => !!adminToken(),
    () => false,
  );
}

/**
 * Whether admin actions should be offered on this device: a token is stored, or the server reports that it runs
 * without one (`/status` → `"admin": "open (dev)"`). The server enforces it either way (`401 admin_required`).
 */
export function useAdmin(): { admin: boolean; hasToken: boolean; open: boolean } {
  const hasToken = useHasToken();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, staleTime: 60_000, retry: false });
  const open = status.data?.admin === "open (dev)";
  return { admin: hasToken || open, hasToken, open };
}

/** Token entry for admin actions; shown to the public in place of the controls. */
export function AdminAccess({ what }: { what: string }) {
  const [token, setToken] = React.useState("");
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 md:flex-row md:items-end md:justify-between">
      <div className="space-y-1">
        <p className="flex items-center gap-2 text-[14px] font-semibold">
          <ShieldCheck className="size-4 text-muted" aria-hidden /> Admin actions
        </p>
        <p className="max-w-xl text-[13px] leading-5 text-muted">{what}</p>
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (token.trim()) setAdminToken(token.trim());
        }}
      >
        <Input type="password" aria-label="Admin token" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Admin token" className="w-56" autoComplete="off" />
        <Button type="submit" variant="outline" disabled={!token.trim()}>
          Unlock
        </Button>
      </form>
    </div>
  );
}

/** Small "lock again" link for a device that stored a token. */
export function AdminLock() {
  const { hasToken } = useAdmin();
  if (!hasToken) return null;
  return (
    <button type="button" onClick={() => setAdminToken(null)} className="text-[12px] text-muted underline underline-offset-2">
      Lock admin actions on this device
    </button>
  );
}
