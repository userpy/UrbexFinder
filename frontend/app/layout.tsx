import type { Metadata } from "next";
import { SessionProvider } from "@/entities/session";
import { Header } from "@/widgets/shell";
import "./globals.css";
export const metadata: Metadata = {
  title: "UrbexFinder — атлас забытых мест",
  description:
    "Исследуйте карту заброшенных мест. Сведения, фотографии и наблюдения сообщества.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body>
        <SessionProvider>
          <Header />
          {children}
        </SessionProvider>
      </body>
    </html>
  );
}
