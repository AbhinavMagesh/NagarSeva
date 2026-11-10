"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, formatDate, type Grievance, type TimelineItem } from "@/lib/api";
import { getSocket } from "@/lib/socket";

const pipelineStages = [
  { id: "media_upload", title: "Media upload" },
  { id: "transcription", title: "Voice transcription" },
  { id: "intake", title: "Issue analysis" },
  { id: "duplicate_check", title: "Duplicate check" },
  { id: "severity", title: "Severity assessment" },
  { id: "routing", title: "Department routing" },
];

function displayResult(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function GrievancePage() {
  const params = useParams<{ id: string }>();
  const [item, setItem] = useState<Grievance | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [error, setError] = useState("");
  const [verifyMessage, setVerifyMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [grievance, events] = await Promise.all([
        api<Grievance>(`/api/v1/grievances/${params.id}`),
        api<TimelineItem[]>(`/api/v1/grievances/${params.id}/timeline`),
      ]);
      setItem(grievance);
      setTimeline(events);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load grievance.");
    }
  }, [params.id]);

  useEffect(() => {
    void refresh();
    const socket = getSocket();
    const update = (data: { id?: string; grievance_id?: string }) => {
      if (data.id === params.id || data.grievance_id === params.id) void refresh();
    };
    ["grievance_updated", "grievance_processed", "grievance_failed", "grievance_escalated", "grievance_processing"].forEach((event) => socket.on(event, update));
    return () => ["grievance_updated", "grievance_processed", "grievance_failed", "grievance_escalated", "grievance_processing"].forEach((event) => socket.off(event, update));
  }, [params.id, refresh]);

  useEffect(() => {
    if (item?.status !== "PROCESSING") return;
    const interval = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(interval);
  }, [item?.status, refresh]);

  const stageEvents = new Map<string, TimelineItem>();
  timeline.filter((event) => event.action === "PIPELINE_STAGE").forEach((event) => {
    if (typeof event.details.stage === "string") stageEvents.set(event.details.stage, event);
  });
  const hasVoiceStage = stageEvents.has("transcription");
  const visibleStages = pipelineStages.filter((stage) => stage.id !== "transcription" || hasVoiceStage);
  const currentStage = visibleStages.find((stage) => stageEvents.get(stage.id)?.details.status === "running");
  const duplicateResult = stageEvents.get("duplicate_check")?.details.result;
  const duplicateWasMerged = isRecord(duplicateResult) && duplicateResult.duplicate_found === true;

  async function verify(isResolved: boolean) {
    setLoading(true);
    setVerifyMessage("");
    try {
      const result = await api<{ result: string }>("/api/v1/verify/" + params.id, {
        method: "POST",
        body: JSON.stringify({ is_resolved: isResolved }),
      });
      setVerifyMessage(result.result === "INCONCLUSIVE" ? "Thanks — your confirmation has been recorded. Three community responses are needed for a resolution decision." : `Community check: ${result.result.replaceAll("_", " ").toLowerCase()}.`);
      await refresh();
    } catch (reason) {
      setVerifyMessage(reason instanceof Error ? reason.message : "Sign in to record your confirmation.");
    } finally {
      setLoading(false);
    }
  }

  if (error) return <div className="page-shell"><div className="error-banner">{error}</div><Link href="/">← Back to dashboard</Link></div>;
  if (!item) return <div className="page-shell"><p className="quiet">Loading public record…</p></div>;

  return (
    <div className="page-shell detail-shell">
      <div className="eyebrow"><Link href="/">DASHBOARD</Link><span>/</span> PUBLIC RECORD</div>
      <section className="detail-heading">
        <div><span className="tracking">{item.tracking_id}</span><h1>{item.title}</h1><p>{item.description}</p></div>
        <span className={`status-pill status-${item.status.toLowerCase()}`}>{item.status.replaceAll("_", " ")}</span>
      </section>
      {item.processing_error && <div className="error-banner">Report processing needs attention: {item.processing_error}</div>}
      {item.status === "PROCESSING" && <div className="processing-banner"><span className="live-dot" /> {currentStage ? `${currentStage.title} in progress…` : "Your report is being analyzed. This page updates automatically."}</div>}
      {item.image_urls?.length > 0 && <div className="detail-images">{item.image_urls.map((url) => <a key={url} href={url} target="_blank" rel="noreferrer"><img src={url} alt="Citizen-submitted civic issue" /></a>)}</div>}
      {(item.status === "PROCESSING" || stageEvents.size > 0) && <section className="panel pipeline-panel">
        <div className="panel-title"><span>{item.status === "PROCESSING" ? "LIVE PROCESSING PIPELINE" : "PROCESSING RESULTS"}</span><span className="panel-index">LIVE</span></div>
        <div className="pipeline-steps">{visibleStages.map((stage, index) => {
          const event = stageEvents.get(stage.id);
          const status = typeof event?.details.status === "string" ? event.details.status : "pending";
          const result = event?.details.result;
          const resultFields = isRecord(result) ? Object.entries(result) : [];
          const skipped = !event && duplicateWasMerged && (stage.id === "severity" || stage.id === "routing");
          return <article className={`pipeline-step pipeline-${skipped ? "skipped" : status}`} key={stage.id}>
            <span className="pipeline-step-number">{index + 1}</span>
            <div className="pipeline-step-content">
              <div className="pipeline-step-heading"><strong>{stage.title}</strong><span>{skipped ? "Skipped — duplicate merged" : status === "pending" ? "Waiting" : status.replaceAll("_", " ")}</span></div>
              {resultFields.length > 0 && <dl className="pipeline-result">{resultFields.map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{displayResult(value)}</dd></div>)}</dl>}
            </div>
          </article>;
        })}</div>
      </section>}
      <div className="detail-grid">
        <section className="panel detail-main">
          <div className="panel-title"><span>TRIAGE ASSESSMENT</span><span className="panel-index">A</span></div>
          <div className="severity-score"><strong>{item.severity_score > 0 ? item.severity_score.toFixed(1) : "—"}</strong><span>/ 10<br /><b>{item.severity_label}</b></span></div>
          <p className="detail-explanation">{item.severity_explanation ?? "A severity assessment will appear here after analysis."}</p>
          <div className="detail-meta"><span>Category</span><strong>{item.category.replaceAll("_", " ")}</strong></div>
          <div className="detail-meta"><span>Responsible department</span><strong>{item.department ?? "Pending triage"}</strong></div>
          <div className="detail-meta"><span>Assigned officer</span><strong>{item.assigned_authority_name ?? (item.department ? "Department queue" : "Pending assignment")}</strong></div>
          <div className="detail-meta"><span>Location</span><strong>{item.address ?? "Location pending"}</strong></div>
          <div className="detail-meta"><span>Community reports</span><strong>{item.report_count}</strong></div>
          {item.sla_deadline && <div className="detail-meta"><span>Target response date</span><strong>{formatDate(item.sla_deadline)}</strong></div>}
          {Object.keys(item.severity_signals ?? {}).filter((key) => typeof item.severity_signals[key] === "number").length > 0 && (
            <div className="signal-list"><h3>Severity signals</h3>{Object.entries(item.severity_signals).filter(([, value]) => typeof value === "number").map(([key, value]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}/10</strong></div>)}</div>
          )}
        </section>
        <aside className="panel timeline-panel">
          <div className="panel-title"><span>PUBLIC TIMELINE</span><span className="panel-index">B</span></div>
          {!timeline.length && <p className="empty-copy">Timeline updates will appear here.</p>}
          <div className="timeline">{timeline.map((event, index) => (
            <div className="timeline-event" key={`${event.action}-${event.created_at}-${index}`}>
              <span className="timeline-dot" /><div><strong>{event.action.replaceAll("_", " ")}</strong><time>{formatDate(event.created_at)}</time>
                {Boolean(event.details.error) && <p className="timeline-error">{String(event.details.error)}</p>}
                {Boolean(event.details.comment) && <p>{String(event.details.comment)}</p>}
              </div>
            </div>
          ))}</div>
          <div className="verification-box"><h3>Is the issue resolved?</h3><p>Confirm what you can see nearby. Community responses are recorded in the public timeline. <Link className="inline-link" href="/account">Create a citizen account or sign in</Link> to respond.</p>
            <div className="verify-actions"><button disabled={loading} onClick={() => void verify(true)}>Yes, resolved</button><button disabled={loading} onClick={() => void verify(false)}>Still an issue</button></div>
            {verifyMessage && <small>{verifyMessage}</small>}
          </div>
        </aside>
      </div>
    </div>
  );
}
