"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, formatDate, type Grievance } from "@/lib/api";
import { getSocket } from "@/lib/socket";

const IssueMap = dynamic(() => import("@/components/IssueMap"), { ssr: false });
type Stats = { total: number; resolved: number; pending: number; sla_breached: number };
const categories: Record<string, string> = {
  ROAD_DAMAGE: "Road damage", WATER_LEAK: "Water & pipelines", SEWAGE: "Sewage & drains",
  ELECTRICITY: "Electricity", POLLUTION: "Pollution", BRIDGE_DAMAGE: "Bridge damage",
  GARBAGE: "Garbage", STREETLIGHT: "Streetlights", OTHER: "Other",
};

export default function Dashboard() {
  const [items, setItems] = useState<Grievance[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [categoriesData, setCategoriesData] = useState<Record<string, number>>({});
  const [departments, setDepartments] = useState<Array<{ department: string; total_assigned: number; total_resolved: number; resolution_rate_pct: number }>>([]);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const [feed, overview, categoryCounts, scorecard] = await Promise.all([
        api<Grievance[]>("/api/v1/dashboard/live-feed?limit=50"),
        api<Stats>("/api/v1/dashboard/stats"),
        api<Record<string, number>>("/api/v1/dashboard/category-breakdown"),
        api<Array<{ department: string; total_assigned: number; total_resolved: number; resolution_rate_pct: number }>>("/api/v1/dashboard/authority-scorecard"),
      ]);
      setItems(feed);
      setStats(overview);
      setCategoriesData(categoryCounts);
      setDepartments(scorecard);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load live dashboard data.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const socket = getSocket();
    const update = () => void refresh();
    socket.on("new_grievance", update);
    socket.on("grievance_updated", update);
    socket.on("grievance_processed", update);
    socket.on("grievance_escalated", update);
    socket.on("grievance_processing", update);
    socket.on("grievance_failed", update);
    return () => {
      socket.off("new_grievance", update);
      socket.off("grievance_updated", update);
      socket.off("grievance_processed", update);
      socket.off("grievance_escalated", update);
      socket.off("grievance_processing", update);
      socket.off("grievance_failed", update);
    };
  }, [refresh]);

  const maxCategory = Math.max(1, ...Object.values(categoriesData));
  return (
    <div className="page-shell">
      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow"><span className="live-dot" /> LIVE PUBLIC REGISTER</div>
          <h1>Better streets start<br />with being <em>heard.</em></h1>
          <p>Report what needs fixing. Follow every issue from community report to public resolution.</p>
          <div className="hero-actions"><Link className="button button-dark" href="/report">Report a civic issue <span>↗</span></Link><span className="hero-note">Photo or voice · Takes about a minute</span></div>
        </div>
        <div className="hero-stamp"><span>PUBLIC</span><strong>01</strong><span>ACCOUNTABILITY</span></div>
      </section>

      {error && <div className="error-banner" role="alert">Live data unavailable: {error}<button onClick={() => void refresh()}>Retry</button></div>}

      <section className="stats-grid" aria-label="Live civic issue statistics">
        {[
          ["ALL REPORTS", stats?.total],
          ["RESOLVED", stats?.resolved],
          ["OPEN ISSUES", stats?.pending],
          ["SLA BREACHED", stats?.sla_breached],
        ].map(([label, value], index) => (
          <article className={`stat-card stat-${index}`} key={label}>
            <span className="stat-label">{label}</span>
            <strong>{value === undefined ? "—" : value.toLocaleString("en-IN")}</strong>
            <span className="stat-caption">{index === 0 ? "in the public register" : index === 1 ? "reported resolved" : index === 2 ? "being tracked now" : "past their target date"}</span>
          </article>
        ))}
      </section>

      <div className="section-heading">
        <div><div className="eyebrow">01 / THE CITY, IN VIEW</div><h2>Issue map</h2></div>
        <span className="quiet">{items.length ? `${items.length} recent reports mapped where location is available` : "Waiting for community reports"}</span>
      </div>
      <section className="dashboard-grid">
        <div className="panel map-panel"><IssueMap items={items} /></div>
        <aside className="panel breakdown-panel">
          <div className="panel-title"><span>REPORTS BY CATEGORY</span><span className="panel-index">A</span></div>
          {Object.entries(categoriesData).sort((a, b) => b[1] - a[1]).slice(0, 7).map(([category, count]) => (
            <div className="bar-row" key={category}>
              <div><span>{categories[category] ?? category}</span><b>{count}</b></div>
              <div className="bar-track"><i style={{ width: `${(count / maxCategory) * 100}%` }} /></div>
            </div>
          ))}
          {!Object.keys(categoriesData).length && <p className="empty-copy">Category totals will appear after reports are processed.</p>}
        </aside>
      </section>

      <section className="dashboard-grid lower-grid">
        <div className="panel feed-panel">
          <div className="panel-title"><span>RECENT COMMUNITY REPORTS</span><span className="panel-index">B</span></div>
          {!items.length && !error && <p className="empty-copy">No reports yet. Be the first to let your community be heard.</p>}
          {items.slice(0, 8).map((issue) => (
            <Link className="feed-item" href={`/grievance/${issue.id}`} key={issue.id}>
              <span className={`severity-dot severity-${issue.severity_label.toLowerCase()}`} />
              <span className="feed-main"><strong>{issue.title}</strong><small>{issue.tracking_id} · {categories[issue.category] ?? issue.category} · {formatDate(issue.created_at)}</small></span>
              <span className={`status-pill status-${issue.status.toLowerCase()}`}>{issue.status.replaceAll("_", " ")}</span>
              <span className="feed-arrow">↗</span>
            </Link>
          ))}
        </div>
        <aside className="panel scorecard-panel">
          <div className="panel-title"><span>DEPARTMENT SCORECARD</span><span className="panel-index">C</span></div>
          {departments.map((dept) => (
            <div className="score-row" key={dept.department}>
              <span>{dept.department}</span><strong>{dept.total_resolved}<small> / {dept.total_assigned}</small></strong>
              <div className="bar-track"><i style={{ width: `${dept.resolution_rate_pct}%` }} /></div>
            </div>
          ))}
          {!departments.length && <p className="empty-copy">Department performance will appear as issues are assigned.</p>}
        </aside>
      </section>
      <section className="closing-note"><span>OPEN BY DESIGN</span><p>Every report has a timeline. Every status change is recorded. Progress belongs to the public.</p></section>
    </div>
  );
}
