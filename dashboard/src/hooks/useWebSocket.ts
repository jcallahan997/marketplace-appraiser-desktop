import { useCallback, useEffect, useRef, useState } from "react";
import type { PipelineStep, WsMessage } from "../types";

/** Default pipeline steps matching graph.py PIPELINE_NODES */
const DEFAULT_STEPS: PipelineStep[] = [
  { node: "scrape_listing", step: 1, label: "Scrape Listing", status: "pending" },
  { node: "analyze_images", step: 2, label: "Analyze Images", status: "pending" },
  { node: "assess_condition", step: 3, label: "Assess Condition", status: "pending" },
  { node: "research_market", step: 4, label: "Research Market", status: "pending" },
  { node: "investigate_seller", step: 5, label: "Investigate Seller", status: "pending" },
  { node: "assess_price", step: 6, label: "Assess Price", status: "pending" },
  { node: "email_report", step: 7, label: "Build Email Report", status: "pending" },
];

export interface RunMetrics {
  cost: number | null;
  duration: number | null;
}

export interface UseWebSocketReturn {
  connected: boolean;
  isRunning: boolean;
  activeRuns: string[];
  runId: string | null;
  steps: PipelineStep[];
  logs: string[];
  error: string | null;
  completedRunId: string | null;
  completedMetrics: RunMetrics | null;
  resetPipeline: () => void;
  focusRun: (runId: string) => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [activeRuns, setActiveRuns] = useState<string[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<PipelineStep[]>(DEFAULT_STEPS);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [completedRunId, setCompletedRunId] = useState<string | null>(null);
  const [completedMetrics, setCompletedMetrics] = useState<RunMetrics | null>(null);
  const [totalSteps, setTotalSteps] = useState(7);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // The "focused" run — we show logs/steps for this run only.
  // Set when user starts an appraisal or selects a run from history.
  const focusedRunIdRef = useRef<string | null>(null);

  const focusRun = useCallback((id: string) => {
    focusedRunIdRef.current = id;
    setRunId(id);
    // Reset display state for the newly focused run
    setSteps(DEFAULT_STEPS.map((s) => ({ ...s, status: "pending" })));
    setLogs([]);
    setError(null);
    setCompletedRunId(null);
    setCompletedMetrics(null);
    setTotalSteps(7);
  }, []);

  const resetPipeline = useCallback(() => {
    focusedRunIdRef.current = null;
    setRunId(null);
    setSteps(DEFAULT_STEPS.map((s) => ({ ...s, status: "pending" })));
    setLogs([]);
    setError(null);
    setCompletedRunId(null);
    setCompletedMetrics(null);
    setTotalSteps(7);
  }, []);

  const handleMessage = useCallback((msg: WsMessage) => {
    switch (msg.type) {
      case "status":
        setIsRunning(msg.is_running);
        if (msg.active_runs) {
          setActiveRuns(msg.active_runs);
        }
        // If we don't have a focused run yet, auto-focus the first active run
        if (msg.run_id && !focusedRunIdRef.current) {
          focusedRunIdRef.current = msg.run_id;
          setRunId(msg.run_id);
        }
        if (msg.total_steps) {
          setTotalSteps(msg.total_steps);
        }
        break;

      case "stdout": {
        // Only show logs for the focused run (or untagged messages)
        const msgRunId = msg.run_id ?? null;
        if (msgRunId === null || msgRunId === focusedRunIdRef.current) {
          setLogs((prev) => [...prev, msg.text]);
        }
        break;
      }

      case "step_start": {
        const msgRunId = msg.run_id ?? null;
        if (msgRunId === null || msgRunId === focusedRunIdRef.current) {
          setIsRunning(true);
          setSteps((prev) =>
            prev.map((s) =>
              s.node === msg.node ? { ...s, status: "running" } : s
            )
          );
        }
        break;
      }

      case "step_complete": {
        const msgRunId = msg.run_id ?? null;
        if (msgRunId === null || msgRunId === focusedRunIdRef.current) {
          setSteps((prev) =>
            prev.map((s) =>
              s.node === msg.node ? { ...s, status: "done" } : s
            )
          );
        }
        break;
      }

      case "pipeline_complete":
        // Always notify when ANY run completes (for history refresh)
        if (msg.run_id === focusedRunIdRef.current) {
          setCompletedRunId(msg.run_id);
          setCompletedMetrics({
            cost: msg.cost ?? null,
            duration: msg.duration ?? null,
          });
          // Mark any remaining running steps as done
          setSteps((prev) =>
            prev.map((s) =>
              s.status === "running" ? { ...s, status: "done" } : s
            )
          );
        }
        // Update active runs list; if none remain, mark as not running
        setActiveRuns((prev) => {
          const next = prev.filter((id) => id !== msg.run_id);
          if (next.length === 0) setIsRunning(false);
          return next;
        });
        break;

      case "error":
        if (msg.run_id === focusedRunIdRef.current) {
          setError(msg.text);
          setIsRunning(false);
          setSteps((prev) =>
            prev.map((s) =>
              s.status === "running" ? { ...s, status: "error" } : s
            )
          );
        }
        break;

      case "done": {
        const msgRunId = msg.run_id ?? null;
        if (msgRunId === null || msgRunId === focusedRunIdRef.current) {
          setIsRunning(false);
        }
        break;
      }

      case "heartbeat":
        break;
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/progress`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      clearTimeout(reconnectTimer.current);
    };

    ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data);
        handleMessage(msg);
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      // Auto-reconnect after 2s
      reconnectTimer.current = setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [handleMessage]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // Return only the steps relevant to the current run
  const visibleSteps = totalSteps < 7
    ? steps.filter((s) => s.step <= totalSteps)
    : steps;

  return {
    connected,
    isRunning,
    activeRuns,
    runId,
    steps: visibleSteps,
    logs,
    error,
    completedRunId,
    completedMetrics,
    resetPipeline,
    focusRun,
  };
}
