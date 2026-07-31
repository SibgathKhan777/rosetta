import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rosetta — decode any video",
  description: "Paste a video URL, get the transcript, the on-screen text, and the teaching behind it.",
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
