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

export interface UseWebSocketReturn {
  connected: boolean;
  isRunning: boolean;
  runId: string | null;
  steps: PipelineStep[];
  logs: string[];
  error: string | null;
  completedRunId: string | null;
  resetPipeline: () => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<PipelineStep[]>(DEFAULT_STEPS);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [completedRunId, setCompletedRunId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const resetPipeline = useCallback(() => {
    setSteps(DEFAULT_STEPS.map((s) => ({ ...s, status: "pending" })));
    setLogs([]);
    setError(null);
    setCompletedRunId(null);
  }, []);

  const handleMessage = useCallback((msg: WsMessage) => {
    switch (msg.type) {
      case "status":
        setIsRunning(msg.is_running);
        setRunId(msg.run_id);
        break;

      case "stdout":
        setLogs((prev) => [...prev, msg.text]);
        break;

      case "step_start":
        setSteps((prev) =>
          prev.map((s) =>
            s.node === msg.node ? { ...s, status: "running" } : s
          )
        );
        break;

      case "step_complete":
        setSteps((prev) =>
          prev.map((s) =>
            s.node === msg.node ? { ...s, status: "done" } : s
          )
        );
        break;

      case "pipeline_complete":
        setIsRunning(false);
        setCompletedRunId(msg.run_id);
        break;

      case "error":
        setError(msg.text);
        setIsRunning(false);
        break;

      case "done":
        setIsRunning(false);
        break;

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

  return {
    connected,
    isRunning,
    runId,
    steps,
    logs,
    error,
    completedRunId,
    resetPipeline,
  };
}
