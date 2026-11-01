import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "NagarSeva — Civic issues, visible progress",
  description: "Report civic issues and follow their progress in real time.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link className="brand" href="/">
            <span className="brand-mark">N</span>
            <span>NagarSeva<small>PUBLIC CIVIC DESK</small></span>
          </Link>
          <nav>
            <Link href="/">Live dashboard</Link>
            <Link href="/report">Report an issue</Link>
            <Link href="/account">Community account</Link>
            <Link href="/authority">Authority desk</Link>
          </nav>
          <Link className="nav-cta" href="/report">File a report <span>↗</span></Link>
        </header>
        <main>{children}</main>
        <footer className="footer">
          <span>NagarSeva · Community reports, public accountability</span>
          <span>Map © OpenStreetMap contributors</span>
        </footer>
      </body>
    </html>
  );
}
