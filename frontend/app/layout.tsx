import type { Metadata } from "next";
import { cookies } from "next/headers";
import { Geist, Geist_Mono } from "next/font/google";
import { Providers } from "@/components/providers";
import { AppLayout } from "@/components/app-layout";
import { LANGUAGE_COOKIE_KEY, resolveLanguage } from "@/lib/i18n/config";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Kardcraft Desktop",
  description: "智能知识管理与Anki制卡平台",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieStore = await cookies();
  const language = resolveLanguage(cookieStore.get(LANGUAGE_COOKIE_KEY)?.value);

  return (
    <html lang={language} suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <Providers initialLanguage={language}>
          <AppLayout>{children}</AppLayout>
        </Providers>
      </body>
    </html>
  );
}
