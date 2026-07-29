import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Video Extraction Platform",
  description: "Paste a video URL, get transcript + on-screen text + metadata",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
