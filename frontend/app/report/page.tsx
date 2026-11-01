"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { API_URL } from "@/lib/api";

function encodeWav(buffer: AudioBuffer): Blob {
  const channelCount = Math.min(buffer.numberOfChannels, 1);
  const source = buffer.getChannelData(0);
  const sampleRate = 16000;
  const ratio = buffer.sampleRate / sampleRate;
  const samples = new Float32Array(Math.ceil(source.length / ratio));
  for (let i = 0; i < samples.length; i++) {
    const sourceIndex = i * ratio;
    const left = Math.floor(sourceIndex);
    const fraction = sourceIndex - left;
    samples[i] = source[left] * (1 - fraction) + (source[Math.min(left + 1, source.length - 1)] ?? 0) * fraction;
  }
  const output = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(output);
  const write = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  write(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); write(8, "WAVE");
  write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, channelCount, true); view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0, offset = 44; i < samples.length; i++, offset += 2) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Blob([output], { type: "audio/wav" });
}

export default function ReportPage() {
  const router = useRouter();
  const [description, setDescription] = useState("");
  const [images, setImages] = useState<File[]>([]);
  const [audio, setAudio] = useState<Blob | null>(null);
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [locationMessage, setLocationMessage] = useState("Add a landmark in your description or share your device location.");
  const [recording, setRecording] = useState(false);
  const [convertingAudio, setConvertingAudio] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recordingMessage, setRecordingMessage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  function getLocation() {
    setLocationMessage("Finding your location…");
    if (!navigator.geolocation) { setLocationMessage("Location is unavailable in this browser."); return; }
    navigator.geolocation.getCurrentPosition(
      ({ coords: position }) => {
        setCoords({ latitude: position.latitude, longitude: position.longitude });
        setLocationMessage(`Location ready · ${position.latitude.toFixed(4)}, ${position.longitude.toFixed(4)}`);
      },
      () => setLocationMessage("Could not access location. Add a nearby landmark in your description instead."),
      { enableHighAccuracy: true, timeout: 12000 },
    );
  }

  async function beginRecording() {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onstop = async () => {
        setConvertingAudio(true);
        try {
          const recorded = new Blob(chunksRef.current, { type: recorder.mimeType });
          const context = new AudioContext();
          const decoded = await context.decodeAudioData(await recorded.arrayBuffer());
          setAudio(encodeWav(decoded));
          await context.close();
          setRecordingMessage("Voice recording ready for transcription.");
        } catch {
          setError("This browser could not convert the recording. Try uploading an audio file or type your report.");
        } finally {
          stream.getTracks().forEach((track) => track.stop());
          setConvertingAudio(false);
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setRecordingMessage("Recording — speak naturally, then select Stop.");
    } catch {
      setError("Microphone access was denied or is unavailable. Use a photo and written description instead.");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    setRecording(false);
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!images.length && !audio && !description.trim()) {
      setError("Add at least one photo, a voice recording, or a written description.");
      return;
    }
    setBusy(true);
    const form = new FormData();
    if (audio) {
      form.append("audio", audio, "voice-report.wav");
      form.append("language_hint", "unknown");
    } else {
      images.forEach((image) => form.append("images", image));
    }
    form.append("description", description);
    if (coords) {
      form.append("latitude", String(coords.latitude));
      form.append("longitude", String(coords.longitude));
    }
    try {
      const token = localStorage.getItem("nagarseva_token");
      const response = await fetch(`${API_URL}/api/v1/grievances/${audio ? "file-voice" : "file-image"}`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? `Could not submit report (${response.status}).`);
      router.push(`/grievance/${result.grievance_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not submit your report.");
      setBusy(false);
    }
  }

  return (
    <div className="page-shell form-shell">
      <div className="eyebrow"><Link href="/">DASHBOARD</Link><span>/</span> FILE A REPORT</div>
      <section className="form-heading"><div><h1>Your street.<br /><em>Your say.</em></h1><p>A photo or a few words helps the right department understand what needs fixing.</p></div><div className="form-step"><span>01</span><small>COMMUNITY<br />REPORT</small></div></section>
      {error && <div className="error-banner" role="alert">{error}</div>}
      <form className="report-form" onSubmit={submit}>
        <section className="form-section">
          <div className="form-section-heading"><span>01</span><div><h2>Show us the issue</h2><p>Upload up to 5 clear photos, or record a voice report.</p></div></div>
          <button type="button" className="upload-zone" onClick={() => inputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); setImages(Array.from(event.dataTransfer.files).filter((file) => file.type.startsWith("image/")).slice(0, 5)); setAudio(null); }}>
            <span className="upload-icon">＋</span><strong>Choose photos or drop them here</strong><small>JPG, PNG or WebP · Up to 5 photos · 10 MB each</small>
          </button>
          <input ref={inputRef} className="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => { setImages(Array.from(event.target.files ?? []).slice(0, 5)); setAudio(null); }} />
          {images.length > 0 && <div className="selected-files">{images.map((image) => <span key={`${image.name}-${image.size}`}>{image.name}<button type="button" onClick={() => setImages((current) => current.filter((entry) => entry !== image))} aria-label={`Remove ${image.name}`}>×</button></span>)}</div>}
          <div className="voice-row">
            <button type="button" className={`button ${recording ? "button-recording" : "button-outline"}`} onClick={recording ? stopRecording : beginRecording}>{recording ? "■ Stop recording" : "● Record a voice report"}</button>
            {audio && <button className="text-button" type="button" onClick={() => { setAudio(null); setRecordingMessage(""); }}>Remove recording ×</button>}
            <span className="quiet">{convertingAudio ? "Preparing audio for transcription…" : recordingMessage || "Speak in your preferred Indian language."}</span>
          </div>
        </section>
        <section className="form-section">
          <div className="form-section-heading"><span>02</span><div><h2>Tell us what happened</h2><p>A landmark or cross street helps locate the issue if GPS is unavailable.</p></div></div>
          <label className="field-label" htmlFor="description">DESCRIPTION / NEARBY LANDMARK</label>
          <textarea id="description" rows={4} maxLength={3000} placeholder="For example: a deep pothole on MG Road, opposite the city library. It is difficult for bikes to pass safely." value={description} onChange={(event) => setDescription(event.target.value)} />
          <div className="location-row"><button type="button" className="button button-outline" onClick={getLocation}>⌖ Use my location</button><span>{locationMessage}</span></div>
        </section>
        <div className="submit-row"><p>Your report is public. Do not include private or identifying information.</p><button className="button button-dark" disabled={busy || recording || convertingAudio}>{busy ? "Sending report…" : "Submit report"} <span>↗</span></button></div>
      </form>
    </div>
  );
}
