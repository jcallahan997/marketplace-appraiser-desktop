import type { PipelineStep, StepStatus } from "../types";

const statusIcon: Record<StepStatus, string> = {
  pending: "○",
  running: "◉",
  done: "✓",
  error: "✗",
};

const statusColor: Record<StepStatus, string> = {
  pending: "text-gray-400",
  running: "text-teal-500 animate-pulse",
  done: "text-green-500",
  error: "text-red-500",
};

const statusBg: Record<StepStatus, string> = {
  pending: "bg-gray-50 border-gray-200",
  running: "bg-teal-50 border-teal-300 shadow-sm",
  done: "bg-green-50 border-green-200",
  error: "bg-red-50 border-red-200",
};

interface Props {
  steps: PipelineStep[];
}

export function PipelineProgress({ steps }: Props) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
        Pipeline Progress
      </h3>
      <div className="space-y-1.5">
        {steps.map((step) => (
          <div
            key={step.node}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-all duration-300 ${statusBg[step.status]}`}
          >
            <span className={`text-lg font-mono ${statusColor[step.status]}`}>
              {statusIcon[step.status]}
            </span>
            <span className="text-xs text-gray-400 font-mono w-4">
              {step.step}
            </span>
            <span
              className={`text-sm ${
                step.status === "running"
                  ? "text-teal-700 font-medium"
                  : step.status === "done"
                  ? "text-green-700"
                  : "text-gray-600"
              }`}
            >
              {step.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
