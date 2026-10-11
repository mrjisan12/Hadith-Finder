import type { Metadata } from "next";
import { Geist, Noto_Naskh_Arabic, Noto_Sans_Bengali, Noto_Serif_Bengali } from "next/font/google";

import { Providers } from "./providers";
import "./globals.css";

const sans = Geist({ variable: "--font-latin", subsets: ["latin"] });
const bengaliSans = Noto_Sans_Bengali({ variable: "--font-bengali", subsets: ["bengali"], weight: ["400", "500", "600", "700"] });
const bengaliSerif = Noto_Serif_Bengali({ variable: "--font-bengali-serif", subsets: ["bengali"], weight: ["400", "500", "600"] });
const arabic = Noto_Naskh_Arabic({ variable: "--font-naskh", subsets: ["arabic"], weight: ["400", "600"] });

export const metadata: Metadata = {
  title: "Hadith Finder — ফাযায়েলে আমল",
  description: "Ask questions about Fazail-e-Amal and verify every answer against the original paragraph, printed page and scanned page.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="bn"
      className={`${sans.variable} ${bengaliSans.variable} ${bengaliSerif.variable} ${arabic.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
