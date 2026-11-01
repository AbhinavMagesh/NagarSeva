"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, formatDate, type Grievance } from "@/lib/api";

type UserInfo = { name: string; role: string };
export default function AuthorityPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [user, setUser] = useState<UserInfo | null>(null);
  const [items, setItems] = useState<Grievance[]>([]);
  const [error, setError] = useState("");

  const loadAssigned = useCallback(async () => {
    try { setItems(await api<Grievance[]>("/api/v1/admin/assigned")); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load assignments."); }
  }, []);
  useEffect(() => {
    if (localStorage.getItem("nagarseva_token")) {
      const stored = localStorage.getItem("nagarseva_user");
      if (stored) setUser(JSON.parse(stored) as UserInfo);
      void loadAssigned();
    }
  }, [loadAssigned]);

  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const result = await api<{ access_token: string; user: UserInfo }>("/api/v1/auth/login", {
        method: "POST", body: JSON.stringify({ email, password }),
      });
      localStorage.setItem("nagarseva_token", result.access_token);
      localStorage.setItem("nagarseva_user", JSON.stringify(result.user));
      setUser(result.user);
      await loadAssigned();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Sign in failed."); }
  }

  async function updateStatus(item: Grievance, status: "IN_PROGRESS" | "RESOLVED") {
    try {
      await api(`/api/v1/grievances/${item.id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
      await loadAssigned();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Status update failed."); }
  }

  function signOut() {
    localStorage.removeItem("nagarseva_token");
    localStorage.removeItem("nagarseva_user");
    setUser(null);
    setItems([]);
  }

  return (
    <div className="page-shell form-shell">
      <div className="eyebrow"><Link href="/">DASHBOARD</Link><span>/</span> AUTHORITY DESK</div>
      {!user ? <>
        <section className="form-heading"><div><h1>Public service.<br /><em>Accountable.</em></h1><p>Sign in with an authorized department account to see assignments and post status updates.</p></div></section>
        <form className="auth-form" onSubmit={signIn}>
          <label className="field-label" htmlFor="email">WORK EMAIL</label><input id="email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
          <label className="field-label" htmlFor="password">PASSWORD</label><input id="password" type="password" required value={password} onChange={(event) => setPassword(event.target.value)} />
          {error && <div className="error-banner">{error}</div>}
          <button className="button button-dark">Sign in <span>↗</span></button>
          <p className="quiet">Authority accounts require the invite code configured by your system administrator.</p>
        </form>
      </> : <>
        <section className="form-heading"><div><h1>Good work,<br /><em>{user.name}.</em></h1><p>Your department queue is visible only to authorized staff.</p></div><button className="button button-outline" onClick={signOut}>Sign out</button></section>
        {error && <div className="error-banner">{error}</div>}
        <div className="authority-list">{items.map((item) => <article className="panel authority-card" key={item.id}>
          <div className="authority-card-top"><span className="tracking">{item.tracking_id}</span><span className={`status-pill status-${item.status.toLowerCase()}`}>{item.status.replaceAll("_", " ")}</span></div>
          <h2>{item.title}</h2><p>{item.description}</p><small>{item.department} · SLA {formatDate(item.sla_deadline)}</small>
          <div className="authority-actions"><Link href={`/grievance/${item.id}`}>Open public record ↗</Link>{item.status !== "IN_PROGRESS" && item.status !== "RESOLVED" && <button onClick={() => void updateStatus(item, "IN_PROGRESS")}>Mark in progress</button>}{item.status !== "RESOLVED" && <button onClick={() => void updateStatus(item, "RESOLVED")}>Mark resolved</button>}</div>
        </article>)}
        {!items.length && <p className="empty-copy">No grievances are currently assigned to your department.</p>}</div>
      </>}
    </div>
  );
}
