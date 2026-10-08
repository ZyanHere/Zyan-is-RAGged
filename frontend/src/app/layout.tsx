import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "myRAG — Evidence-grounded AI",
  description:
    "Ask questions about your documents. Every answer is grounded in retrieved evidence with citations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {/* The store's client boundary. Kept around `{children}` rather than
            around `<html>` so the document itself stays a Server Component —
            the depth matters, per the Next.js server/client boundary guide. */}
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
