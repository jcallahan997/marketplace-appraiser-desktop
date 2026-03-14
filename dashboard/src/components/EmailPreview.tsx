import { useEffect, useState } from "react";

interface Props {
  runId: string | null;
}

export function EmailPreview({ runId }: Props) {
  const [html, setHtml] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) {
      setHtml(null);
      setStatus(null);
      return;
    }
    setLoading(true);

    // Fetch both the preview HTML and the run status
    Promise.all([
      fetch(`/api/runs/${runId}/preview`).then((res) =>
        res.ok ? res.text() : null
      ),
      fetch(`/api/runs/${runId}`).then((res) =>
        res.ok ? res.json() : null
      ),
    ])
      .then(([previewHtml, runData]) => {
        setHtml(previewHtml);
        setStatus(runData?.status || null);
      })
      .catch(() => {
        setHtml(null);
        setStatus(null);
      })
      .finally(() => setLoading(false));
  }, [runId]);

  if (!runId) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        Complete an appraisal to see the email preview
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        Loading preview...
      </div>
    );
  }

  if (!html) {
    const message =
      status === "failed" || status === "stale"
        ? "This run failed before generating a report."
        : status === "running"
        ? "Report will appear here when the pipeline completes."
        : "No preview available for this run.";

    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-400 text-sm gap-2">
        <span>{message}</span>
        {status === "failed" && (
          <span className="text-xs text-gray-300">
            Check the console output for error details.
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Email Preview
      </h3>
      <div className="flex-1 bg-white rounded-lg border border-gray-200 overflow-hidden min-h-0">
        <iframe
          srcDoc={html}
          sandbox="allow-same-origin"
          title="Email Preview"
          className="w-full h-full border-0"
        />
      </div>
    </div>
  );
}
