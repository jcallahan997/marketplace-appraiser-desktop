import { useCallback, useEffect, useState } from "react";
import { ConsoleOutput } from "./components/ConsoleOutput";
import { Controls } from "./components/Controls";
import { EmailPreview } from "./components/EmailPreview";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { PipelineProgress } from "./components/PipelineProgress";
import { RunHistory } from "./components/RunHistory";
import { StatusBar } from "./components/StatusBar";
import { useAppraisal } from "./hooks/useAppraisal";
import { useWebSocket } from "./hooks/useWebSocket";

type Tab = "console" | "email" | "feedback" | "history";

function App() {
  const ws = useWebSocket();
  const api = useAppraisal();
  const [activeTab, setActiveTab] = useState<Tab>("console");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // When a run completes, refresh history and switch to email tab
  useEffect(() => {
    if (ws.completedRunId) {
      api.refreshRuns();
      setSelectedRunId(ws.completedRunId);
      setActiveTab("email");
    }
  }, [ws.completedRunId]);

  const handleStart = useCallback(
    async (url: string, sendEmail: boolean) => {
      ws.resetPipeline();
      setActiveTab("console");
      const runId = await api.startAppraisal(url, sendEmail);
      if (runId) {
        setSelectedRunId(runId);
        ws.focusRun(runId);
      }
    },
    [ws, api]
  );

  const handleSendEmail = useCallback(async (): Promise<boolean> => {
    if (selectedRunId) {
      return api.sendEmail(selectedRunId);
    }
    return false;
  }, [selectedRunId, api]);

  const handleSelectRun = useCallback(
    (runId: string) => {
      setSelectedRunId(runId);
      setActiveTab("email");
    },
    []
  );

  const tabClass = (tab: Tab) =>
    `px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
      activeTab === tab
        ? "bg-white text-teal-700 border-t border-x border-gray-200"
        : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
    }`;

  return (
    <div className="h-screen flex flex-col bg-gray-100">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-start justify-between gap-6">
          <div className="flex-1">
            <div className="flex items-center justify-between">
              <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                <span className="text-teal-600">&#9672;</span> Marketplace Appraiser
              </h1>
              <a
                href="http://localhost:3002/project/marketplace-appraiser"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 hover:text-gray-700 transition-colors"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
                Langfuse
              </a>
            </div>
            <div className="mt-3">
              <Controls
                onStart={handleStart}
                onSendEmail={handleSendEmail}
                isRunning={ws.isRunning}
                hasCompletedRun={!!ws.completedRunId}
                loading={api.loading}
              />
            </div>
          </div>
        </div>
        {api.error && (
          <div className="mt-2 px-3 py-2 bg-red-50 text-red-700 text-sm rounded-lg border border-red-200 flex items-center justify-between">
            <span>{api.error}</span>
            {api.error.includes("already running") && (
              <button
                onClick={() => api.resetPipeline()}
                className="ml-3 px-3 py-1 bg-red-600 text-white text-xs font-medium rounded hover:bg-red-700 transition-colors"
              >
                Force Reset
              </button>
            )}
          </div>
        )}
      </header>

      {/* Main content */}
      <div className="flex-1 flex min-h-0">
        {/* Left sidebar -- pipeline progress + run history */}
        <aside className="w-72 bg-white border-r border-gray-200 p-4 flex flex-col gap-6 overflow-y-auto">
          <PipelineProgress steps={ws.steps} />
          <RunHistory
            runs={api.runs}
            onSelect={handleSelectRun}
            selectedRunId={selectedRunId}
          />
        </aside>

        {/* Right panel -- tabbed content */}
        <main className="flex-1 flex flex-col min-h-0">
          {/* Tabs */}
          <div className="flex gap-1 px-4 pt-3 bg-gray-100">
            <button
              className={tabClass("console")}
              onClick={() => setActiveTab("console")}
            >
              Console
            </button>
            <button
              className={tabClass("email")}
              onClick={() => setActiveTab("email")}
            >
              Email Preview
            </button>
            <button
              className={tabClass("feedback")}
              onClick={() => setActiveTab("feedback")}
            >
              Feedback
            </button>
            <button
              className={tabClass("history")}
              onClick={() => {
                setActiveTab("history");
                api.refreshRuns();
              }}
            >
              History
            </button>
          </div>

          {/* Tab content */}
          <div className="flex-1 p-4 min-h-0">
            {activeTab === "console" && <ConsoleOutput logs={ws.logs} />}
            {activeTab === "email" && <EmailPreview runId={selectedRunId} />}
            {activeTab === "feedback" && (
              <div className="max-w-lg">
                <FeedbackPanel runId={selectedRunId} />
              </div>
            )}
            {activeTab === "history" && (
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
                  All Runs
                </h3>
                <div className="space-y-2 overflow-y-auto max-h-full">
                  {api.runs.length === 0 ? (
                    <p className="text-gray-400 text-sm italic">
                      No runs yet. Start an appraisal above.
                    </p>
                  ) : (
                    api.runs.map((run) => (
                      <div
                        key={run.run_id}
                        className="bg-white rounded-lg border border-gray-200 p-4 cursor-pointer hover:border-teal-300 transition-colors"
                        onClick={() => handleSelectRun(run.run_id)}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-gray-800">
                            {run.item_name || "Untitled"}
                          </span>
                          <span
                            className={`text-xs font-bold px-2 py-0.5 rounded ${
                              run.recommendation === "BUY"
                                ? "bg-green-100 text-green-700"
                                : run.recommendation === "NEGOTIATE"
                                ? "bg-yellow-100 text-yellow-700"
                                : run.recommendation === "PASS"
                                ? "bg-red-100 text-red-700"
                                : "bg-gray-100 text-gray-600"
                            }`}
                          >
                            {run.recommendation || run.status}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 mt-1 truncate">
                          {run.listing_url}
                        </p>
                        <div className="flex items-center gap-3 mt-0.5">
                          <span className="text-xs text-gray-400">
                            {run.started_at
                              ? new Date(run.started_at * 1000).toLocaleString()
                              : ""}
                          </span>
                          {run.langfuse_total_cost != null && (
                            <span className="text-xs text-teal-600 font-mono">
                              ${run.langfuse_total_cost.toFixed(3)}
                            </span>
                          )}
                          {run.langfuse_latency != null && (
                            <span className="text-xs text-gray-500 font-mono">
                              {run.langfuse_latency < 60
                                ? `${Math.round(run.langfuse_latency)}s`
                                : `${Math.floor(run.langfuse_latency / 60)}m ${Math.round(run.langfuse_latency % 60)}s`}
                            </span>
                          )}
                          {run.langfuse_trace_url && (
                            <a
                              href={run.langfuse_trace_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-xs text-teal-500 hover:text-teal-700 hover:underline"
                            >
                              View Trace ↗
                            </a>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Status bar */}
      <StatusBar
        steps={ws.steps}
        isRunning={ws.isRunning}
        connected={ws.connected}
        error={ws.error}
        completedMetrics={ws.completedMetrics}
      />
    </div>
  );
}

export default App;
