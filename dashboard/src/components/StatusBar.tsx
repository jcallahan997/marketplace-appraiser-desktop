import { useEffect, useState } from "react";
import type { PipelineStep } from "../types";
import type { RunMetrics } from "../hooks/useWebSocket";

interface Props {
  steps: PipelineStep[];
  isRunning: boolean;
  connected: boolean;
  error: string | null;
  completedMetrics: RunMetrics | null;
}

function formatCost(cost: number | null): string {
  if (cost === null || cost === undefined) return "";
  return `$${cost.toFixed(4)}`;
}

function formatDuration(secs: number | null): string {
  if (secs === null || secs === undefined) return "";
  if (secs < 60) return `${Math.round(secs)}s`;
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  return `${m}m ${s}s`;
}

export function StatusBar({ steps, isRunning, connected, error, completedMetrics }: Props) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!isRunning) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [isRunning]);

  const currentStep = steps.find((s) => s.status === "running");
  const completedCount = steps.filter((s) => s.status === "done").length;
  const totalSteps = steps.length;

  const formatElapsed = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  const isComplete = completedCount === totalSteps && completedCount > 0;

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-gray-900 text-white text-sm">
      <div className="flex items-center gap-3">
        {/* Connection indicator */}
        <span
          className={`w-2 h-2 rounded-full ${
            connected ? "bg-green-400" : "bg-red-400"
          }`}
          title={connected ? "Connected" : "Disconnected"}
        />

        {isRunning && currentStep ? (
          <span>
            Step {currentStep.step}/{totalSteps} — {currentStep.label}
          </span>
        ) : error ? (
          <span className="text-red-400 max-w-md truncate" title={error}>Error: {error}</span>
        ) : isComplete ? (
          <span className="text-green-400 flex items-center gap-2">
            <span>✅ Appraisal complete</span>
            {completedMetrics?.cost != null && (
              <span className="text-teal-300 font-mono text-xs">
                · {formatCost(completedMetrics.cost)}
              </span>
            )}
            {completedMetrics?.duration != null && (
              <span className="text-gray-400 font-mono text-xs">
                · {formatDuration(completedMetrics.duration)}
              </span>
            )}
          </span>
        ) : (
          <span className="text-gray-400">Ready</span>
        )}
      </div>

      <div className="flex items-center gap-4 text-gray-400">
        {isRunning && (
          <span className="font-mono">{formatElapsed(elapsed)}</span>
        )}
        <span>
          {completedCount}/{totalSteps} steps
        </span>
      </div>
    </div>
  );
}
