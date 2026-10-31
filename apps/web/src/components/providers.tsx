"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";
import { ApiError, ApiOfflineError } from "@/lib/api";
import { useMotionReady } from "@/lib/motion";
import { Toaster } from "./ui/toast";

export function Providers({ children }: { children: React.ReactNode }) {
  useMotionReady();
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (count, err) => {
              if (err instanceof ApiOfflineError) return count < 1;
              if (err instanceof ApiError && err.status < 500) return false;
              return count < 2;
            },
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster />
    </QueryClientProvider>
  );
}
