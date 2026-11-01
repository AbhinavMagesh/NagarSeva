"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type AuthResult = { access_token: string; user: { id: string; name: string; email: string; role: string } };

export default function AccountPage() {
  const [mode, setMode] = useState<"register" | "login">("register");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [user, setUser] = useState<AuthResult["user"] | null>(null);
  useEffect(() => {
    const saved = localStorage.getItem("nagarseva_user");
    try { if (saved) setUser(JSON.parse(saved) as AuthResult["user"]); } catch { localStorage.removeItem("nagarseva_user"); }
  }, []);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const payload = mode === "register"
        ? { name, email, password, role: "citizen" }
        : { email, password };
      const result = await api<AuthResult>(`/api/v1/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      localStorage.setItem("nagarseva_token", result.access_token);
      localStorage.setItem("nagarseva_user", JSON.stringify(result.user));
      setUser(result.user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account request failed.");
    }
  }

  async function shareLocation() {
    setError("");
    if (!navigator.geolocation) { setError("Location is unavailable in this browser."); return; }
    navigator.geolocation.getCurrentPosition(async ({ coords }) => {
      try {
        const query = new URLSearchParams({ latitude: String(coords.latitude), longitude: String(coords.longitude) });
        await api<{ updated: boolean }>(`/api/v1/users/location?${query}`, { method: "PUT" });
        setError("Your nearby location is saved for issue verification.");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not save your location.");
      }
    }, () => setError("Could not access location. Check your browser permissions."));
  }

  function signOut() {
    localStorage.removeItem("nagarseva_token");
    localStorage.removeItem("nagarseva_user");
    setUser(null);
  }

  return (
    <div className="page-shell form-shell">
      <div className="eyebrow"><Link href="/">DASHBOARD</Link><span>/</span> COMMUNITY ACCOUNT</div>
      <section className="form-heading"><div><h1>Many eyes.<br /><em>Better follow-through.</em></h1><p>Create a citizen account to confirm whether nearby issues are resolved and help keep the public record up to date.</p></div></section>
      {user ? <section className="panel account-panel">
        <span className="tracking">SIGNED IN AS</span><h2>{user.name}</h2><p>{user.email}</p>
        <div className="account-actions"><button className="button button-outline" onClick={() => void shareLocation()}>⌖ Share my location</button><button className="text-button" onClick={signOut}>Sign out</button></div>
        {error && <p className="account-message">{error}</p>}
      </section> : <>
        <div className="account-tabs"><button className={mode === "register" ? "selected" : ""} onClick={() => setMode("register")}>Create citizen account</button><button className={mode === "login" ? "selected" : ""} onClick={() => setMode("login")}>Sign in</button></div>
        <form className="auth-form" onSubmit={submit}>
          {mode === "register" && <><label className="field-label" htmlFor="name">YOUR NAME</label><input id="name" required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} /></>}
          <label className="field-label" htmlFor="email">EMAIL</label><input id="email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
          <label className="field-label" htmlFor="password">PASSWORD</label><input id="password" type="password" required minLength={10} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} />
          {error && <div className="error-banner">{error}</div>}
          <button className="button button-dark">{mode === "register" ? "Create account" : "Sign in"} <span>↗</span></button>
        </form>
      </>}
    </div>
  );
}
