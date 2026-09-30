"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { api, type CaptureDetail } from "@/lib/api";
import { formatBytes, formatMs, formatNumber, workerLabel } from "@/lib/format";
import { ChartCard } from "@/components/charts/ChartCard";
import { SpikeTimeline } from "@/components/charts/SpikeTimeline";
import { Alert, Loading, buttonClass } from "@/components/ui";

const seconds = (v: number) => `${+v.toFixed(v < 10 ? 2 : 1)} s`;

export function CaptureDrawer({ runId, index, onClose }: { runId: string; index: number; onClose: () => void }) {
  const [detail, setDetail] = useState<CaptureDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<CaptureDetail>(`/data-collector/runs/${runId}/captures/${index}`)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [runId, index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const m = detail?.metrics;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-y-0 right-0 flex w-full max-w-3xl flex-col border-l border-hairline bg-page shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-hairline bg-surface px-6 py-4">
          <div>
            <div className="text-xs font-medium text-ink-3">
              {detail?.category ?? "Capture"}
              {detail?.worker != null && ` · ${workerLabel(detail.worker, detail.gpus)}`}
            </div>
            <h2 className="text-lg font-semibold tracking-tight">
              Prompt #{String(detail?.prompt ?? "").padStart(2, "0")}
              {detail?.iteration != null && <span className="font-normal text-ink-3"> · iteration {detail.iteration}</span>}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={`/api/data-collector/runs/${runId}/captures/${index}/pcap`}
              className={buttonClass("secondary", "sm")}
              download
            >
              Download PCAP
            </a>
            <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Close">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-6">
          {error && <Alert>{error}</Alert>}
          {!detail && !error && <Loading />}
          {detail && m && (
            <>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-hairline bg-[var(--hairline)] sm:grid-cols-4">
                {[
                  ["Stream packets", formatNumber(m.stream_packets ?? null, 0)],
                  ["Stream bytes", formatBytes(m.stream_bytes)],
                  ["First event", formatMs(m.ttft_ms)],
                  ["Events", formatNumber(m.events ?? null, 0)],
                  ["Events / s", m.events_per_s != null ? formatNumber(m.events_per_s) : "—"],
                  ["Median packet", m.median_packet_bytes != null ? `${m.median_packet_bytes} B` : "—"],
                  ["Median gap", formatMs(m.median_gap_ms)],
                  ["All traffic", `${formatNumber(m.packets ?? null, 0)} pkts`],
                ].map(([label, value]) => (
                  <div key={label} className="bg-surface px-4 py-3">
                    <dt className="text-[11px] text-ink-3">{label}</dt>
                    <dd className="mt-0.5 text-base font-semibold">{value}</dd>
                  </div>
                ))}
              </dl>

              <ChartCard
                title="Response stream on the wire"
                subtitle="Each stem is one server → client packet: when it was sent and its payload size"
                table={{
                  columns: ["Packet", "Time", "Payload"],
                  rows: detail.stream_timeline.map(([t, size], i) => [i + 1, seconds(t), `${size} B`]),
                }}
                footer={detail.downsampled ? "Long stream: every other point is shown." : undefined}
              >
                {detail.stream_timeline.length > 0 ? (
                  <SpikeTimeline
                    points={detail.stream_timeline}
                    color="var(--accent)"
                    formatX={seconds}
                    formatY={(v) => `${Math.round(v)} B`}
                    itemLabel="Packet"
                    ariaLabel="Stream packets over time"
                  />
                ) : (
                  <p className="py-10 text-center text-sm text-ink-3">No stream packets in this capture.</p>
                )}
              </ChartCard>

              {detail.events.length > 0 && (
                <ChartCard
                  title="Events at the client"
                  subtitle="Each stem is one SSE event: when it arrived and the time since the previous one"
                  table={{
                    columns: ["Event", "Time", "Since previous", "Text"],
                    rows: detail.events.map(([t, dt, text], i) => [i + 1, seconds(t), formatMs(dt), JSON.stringify(text)]),
                  }}
                >
                  <SpikeTimeline
                    points={detail.events.map(([t, dt]) => [t, dt])}
                    color="var(--accent)"
                    formatX={seconds}
                    formatY={formatMs}
                    itemLabel="Event"
                    ariaLabel="Client events over time"
                  />
                </ChartCard>
              )}

              <div className="grid gap-4 md:grid-cols-2">
                <TextBlock title="Prompt" text={detail.prompt_text} />
                <TextBlock title="Response" text={detail.response ?? "Not recorded for this capture."} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function TextBlock({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-2xl border border-hairline bg-surface p-4">
      <div className="mb-2 text-xs font-medium text-ink-3">{title}</div>
      <p className="max-h-72 overflow-y-auto text-sm leading-relaxed whitespace-pre-wrap text-ink-2">{text}</p>
    </div>
  );
}
