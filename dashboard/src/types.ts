/** WebSocket message types from the server */
export type WsMessage =
  | { type: "status"; is_running: boolean; run_id: string | null; current_step: number; total_steps: number }
  | { type: "stdout"; text: string }
  | { type: "step_start"; node: string; step: number; label: string }
  | { type: "step_complete"; node: string; step: number; label: string }
  | { type: "pipeline_complete"; run_id: string }
  | { type: "error"; text: string; run_id: string }
  | { type: "done" }
  | { type: "heartbeat" };

/** Pipeline step state for the progress display */
export type StepStatus = "pending" | "running" | "done" | "error";

export interface PipelineStep {
  node: string;
  step: number;
  label: string;
  status: StepStatus;
}

/** Run history entry from GET /api/runs */
export interface RunSummary {
  run_id: string;
  listing_url: string;
  item_name: string;
  status: string;
  started_at: number | null;
  finished_at: number | null;
  report_subject: string | null;
  recommendation: string;
}
