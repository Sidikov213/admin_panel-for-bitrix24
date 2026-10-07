import type { Metadata } from "next";
import { DM_Sans, Source_Serif_4 } from "next/font/google";
import { QueryProvider } from "@/components/providers/query-provider";
import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin", "latin-ext"],
  variable: "--font-dm-sans",
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  subsets: ["latin", "latin-ext"],
  variable: "--font-source-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Focus Analytics",
  description: "Корпоративная аналитика продаж",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={`${dmSans.variable} ${sourceSerif.variable}`}>
      <body className="min-h-screen antialiased">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
