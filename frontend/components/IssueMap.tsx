"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Grievance } from "@/lib/api";

const colors: Record<string, string> = {
  CRITICAL: "#d34c37",
  HIGH: "#e8884c",
  MEDIUM: "#d5a840",
  LOW: "#458a70",
  PENDING: "#75909a",
};

export default function IssueMap({ items }: { items: Grievance[] }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = L.map(container.current, { scrollWheelZoom: false }).setView([20.5937, 78.9629], 5);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map);
    const markers = L.layerGroup().addTo(map);
    mapRef.current = map;
    markersRef.current = markers;
    return () => {
      map.remove();
      mapRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    const group = markersRef.current;
    if (!group) return;
    group.clearLayers();
    items.forEach((issue) => {
      if (issue.lat === null || issue.lng === null) return;
      L.circleMarker([issue.lat, issue.lng], {
        radius: 7 + issue.severity_score * 0.45,
        color: "#fff",
        weight: 2,
        fillColor: colors[issue.severity_label] ?? colors.PENDING,
        fillOpacity: 0.9,
      }).bindPopup(
        `<strong>${issue.tracking_id}</strong><br>${issue.title.replace(/[<>&"]/g, "")}` +
        `<br>${issue.severity_label} · ${issue.status}`,
      ).addTo(group);
    });
  }, [items]);

  return <div className="map" ref={container} aria-label="Map of reported civic issues" />;
}
