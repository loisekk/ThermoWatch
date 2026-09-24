/**
 * TanStack Query client — server-state policy for the analyst console.
 * Reviews NEVER auto-retry (a retry could double-submit; idempotency keys
 * cover timeouts, but a fresh mutation after a hard error must be deliberate).
 */
import { QueryClient } from '@tanstack/react-query';
import { V2ApiError } from '@/services/api/v2Client';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000, // 15 s — incident data is near-real-time
      gcTime: 5 * 60_000, // 5 min garbage collection
      retry: (failureCount, error) => {
        if (error instanceof V2ApiError) {
          // Never retry 4xx client errors — only 5xx and network/timeout.
          if (error.status >= 400 && error.status < 500) return false;
        }
        return failureCount < 2;
      },
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: false, // reviews must NOT auto-retry (idempotency safety)
    },
  },
});
