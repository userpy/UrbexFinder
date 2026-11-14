import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { SessionProvider } from "@/entities/session";
import { Header } from "@/widgets/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "UrbexFinder — атлас забытых мест",
  description:
    "Исследуйте карту заброшенных мест. Сведения, фотографии и наблюдения сообщества.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#000000",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body>
        <Script
          src="https://telegram.org/js/telegram-web-app.js"
          strategy="beforeInteractive"
        />
        <div className="app-shell">
          <SessionProvider>
            <div className="app-content">
              <Header />
              {children}
            </div>
          </SessionProvider>
        </div>
      </body>
    </html>
  );
}
