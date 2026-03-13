import { useCallback, useEffect, useState } from "react";
import { ConsoleOutput } from "./components/ConsoleOutput";
import { Controls } from "./components/Controls";
import { EmailPreview } from "./components/EmailPreview";
import { PipelineProgress } from "./components/PipelineProgress";
import { RunHistory } from "./components/RunHistory";
import { StatusBar } from "./components/StatusBar";
import { useAppraisal } from "./hooks/useAppraisal";
import { useWebSocket } from "./hooks/useWebSocket";

type Tab = "console" | "email" | "history";

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
      }
    },
    [ws, api]
  );

  const handleSendEmail = useCallback(async () => {
    if (selectedRunId) {
      await api.sendEmail(selectedRunId);
    }
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
            <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
              <span className="text-teal-600">&#9672;</span> Marketplace Appraiser
            </h1>
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
          <div className="mt-2 px-3 py-2 bg-red-50 text-red-700 text-sm rounded-lg border border-red-200">
            {api.error}
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
                            {run.item_name || "Unknown"}
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
                        <p className="text-xs text-gray-400 mt-0.5">
                          {run.started_at
                            ? new Date(run.started_at * 1000).toLocaleString()
                            : ""}
                        </p>
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
      />
    </div>
  );
}

export default App;
