export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Grievance = {
  id: string;
  tracking_id: string;
  title: string;
  description: string;
  category: string;
  lat: number | null;
  lng: number | null;
  address: string | null;
  severity_score: number;
  severity_label: string;
  severity_explanation: string | null;
  severity_signals: Record<string, number | string>;
  status: string;
  sla_deadline: string | null;
  report_count: number;
  department: string | null;
  assigned_authority_name: string | null;
  image_urls: string[];
  processing_error: string | null;
  created_at: string | null;
};

export type TimelineItem = { action: string; details: Record<string, unknown>; created_at: string };

export function authHeaders(): HeadersInit {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem("nagarseva_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail ?? payload.message ?? `Request failed (${response.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload as T;
}

export function formatDate(value: string | null): string {
  if (!value) return "Just now";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
