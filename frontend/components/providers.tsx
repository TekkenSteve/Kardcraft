'use client';

import { type SupportedLanguage } from "@/lib/i18n/config";
import { createI18nInstance } from "@/lib/i18n/client";
import { RunSystemProvider } from '@/lib/run/system';
import { SessionProvider } from '@/lib/session/system';
import { ThemeProvider } from '@/lib/theme-provider';
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { useMemo } from 'react';
import { I18nextProvider } from 'react-i18next';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export function Providers({
  children,
  initialLanguage,
}: {
  children: React.ReactNode;
  initialLanguage: SupportedLanguage;
}) {
  const i18n = useMemo(() => createI18nInstance(initialLanguage), [initialLanguage]);

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <RunSystemProvider>
          <ThemeProvider>
            <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
          </ThemeProvider>
        </RunSystemProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
