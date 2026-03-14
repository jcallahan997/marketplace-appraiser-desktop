import type { RunSummary } from "../types";

const recBadge: Record<string, { bg: string; text: string }> = {
  BUY: { bg: "bg-green-100 text-green-700", text: "BUY" },
  NEGOTIATE: { bg: "bg-yellow-100 text-yellow-700", text: "NEGOTIATE" },
  PASS: { bg: "bg-red-100 text-red-700", text: "PASS" },
  REVIEW: { bg: "bg-gray-100 text-gray-600", text: "REVIEW" },
};

function formatTime(ts: number | null): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function relativeTime(ts: number | null): string {
  if (!ts) return "";
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  if (secs < 604800) return `${Math.floor(secs / 86400)}d ago`;
  return "";
}

const statusStyles: Record<string, string> = {
  completed: "text-green-500",
  failed: "text-red-500",
  running: "text-yellow-500",
  stale: "text-gray-400 line-through",
  unknown: "text-gray-400",
};

const statusLabels: Record<string, string> = {
  completed: "completed",
  failed: "failed",
  running: "running",
  stale: "expired",
  unknown: "unknown",
};

interface Props {
  runs: RunSummary[];
  onSelect: (runId: string) => void;
  selectedRunId: string | null;
}

export function RunHistory({ runs, onSelect, selectedRunId }: Props) {
  if (runs.length === 0) {
    return (
      <div className="text-sm text-gray-400 italic py-4 text-center">
        No previous runs
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Run History
      </h3>
      <div className="space-y-1">
        {runs.map((run) => {
          const badge = recBadge[run.recommendation] || null;
          const isSelected = run.run_id === selectedRunId;
          const status = run.status || "unknown";
          const relative = relativeTime(run.started_at);
          return (
            <button
              key={run.run_id}
              onClick={() => onSelect(run.run_id)}
              className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                isSelected
                  ? "bg-teal-50 border-teal-300"
                  : status === "stale"
                  ? "bg-gray-50 border-gray-200 opacity-60 hover:opacity-80"
                  : "bg-white border-gray-200 hover:bg-gray-50"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-gray-800 truncate flex-1" title={run.item_name || "Untitled"}>
                  {run.item_name || "Untitled"}
                </span>
                {badge && run.recommendation && (
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded ${badge.bg}`}
                  >
                    {badge.text}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-gray-400" title={formatTime(run.started_at)}>
                  {relative || formatTime(run.started_at)}
                </span>
                <span className={`text-xs ${statusStyles[status] || statusStyles.unknown}`}>
                  {statusLabels[status] || status}
                </span>
                {run.langfuse_total_cost != null && (
                  <span className="text-xs text-teal-600 font-mono">
                    ${run.langfuse_total_cost.toFixed(3)}
                  </span>
                )}
                {run.langfuse_latency != null && (
                  <span className="text-xs text-gray-400 font-mono">
                    {run.langfuse_latency < 60
                      ? `${Math.round(run.langfuse_latency)}s`
                      : `${Math.floor(run.langfuse_latency / 60)}m ${Math.round(run.langfuse_latency % 60)}s`}
                  </span>
                )}
              </div>
              {run.langfuse_trace_url && (
                <div className="mt-0.5">
                  <a
                    href={run.langfuse_trace_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs text-teal-500 hover:text-teal-700 hover:underline"
                  >
                    View Trace ↗
                  </a>
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
