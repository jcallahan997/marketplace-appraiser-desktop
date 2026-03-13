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
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {runs.map((run) => {
          const badge = recBadge[run.recommendation] || recBadge.REVIEW;
          const isSelected = run.run_id === selectedRunId;
          return (
            <button
              key={run.run_id}
              onClick={() => onSelect(run.run_id)}
              className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                isSelected
                  ? "bg-teal-50 border-teal-300"
                  : "bg-white border-gray-200 hover:bg-gray-50"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-gray-800 truncate flex-1">
                  {run.item_name || "Unknown"}
                </span>
                {run.recommendation && (
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded ${badge.bg}`}
                  >
                    {badge.text}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-gray-400">
                  {formatTime(run.started_at)}
                </span>
                <span
                  className={`text-xs ${
                    run.status === "completed"
                      ? "text-green-500"
                      : run.status === "failed"
                      ? "text-red-500"
                      : "text-yellow-500"
                  }`}
                >
                  {run.status}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
