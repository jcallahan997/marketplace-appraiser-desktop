import { useEffect, useState } from "react";

interface Props {
  runId: string | null;
}

export function EmailPreview({ runId }: Props) {
  const [html, setHtml] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!runId) {
      setHtml(null);
      return;
    }
    setLoading(true);
    fetch(`/api/runs/${runId}/preview`)
      .then((res) => (res.ok ? res.text() : null))
      .then((data) => setHtml(data))
      .catch(() => setHtml(null))
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
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        No preview available for this run
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
