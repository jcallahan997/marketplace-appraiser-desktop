import { useEffect, useState } from "react";

interface Props {
  onStart: (url: string, sendEmail: boolean) => void;
  onSendEmail: () => void;
  isRunning: boolean;
  hasCompletedRun: boolean;
  loading: boolean;
}

export function Controls({
  onStart,
  onSendEmail,
  isRunning,
  hasCompletedRun,
  loading,
}: Props) {
  const [url, setUrl] = useState("");
  const [sendEmail, setSendEmail] = useState(false);

  // Listen for Electron bridge URL auto-fill
  useEffect(() => {
    const bridge = (window as unknown as Record<string, unknown>).electronBridge as
      | { setListingCallback?: (cb: (url: string) => void) => void }
      | undefined;
    if (bridge?.setListingCallback) {
      bridge.setListingCallback((detectedUrl: string) => setUrl(detectedUrl));
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || isRunning) return;
    onStart(url.trim(), sendEmail);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label
          htmlFor="listing-url"
          className="block text-sm font-medium text-gray-700 mb-1"
        >
          Facebook Marketplace URL
        </label>
        <input
          id="listing-url"
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.facebook.com/marketplace/item/..."
          disabled={isRunning}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm
                     focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent
                     disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      </div>

      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={isRunning || loading || !url.trim()}
          className="px-5 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg
                     hover:bg-teal-700 disabled:bg-gray-300 disabled:cursor-not-allowed
                     transition-colors"
        >
          {isRunning ? "Running..." : loading ? "Starting..." : "Start Appraisal"}
        </button>

        {hasCompletedRun && (
          <button
            type="button"
            onClick={onSendEmail}
            className="px-4 py-2 bg-white text-teal-600 text-sm font-medium rounded-lg
                       border border-teal-300 hover:bg-teal-50 transition-colors"
          >
            Re-send Email
          </button>
        )}

        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={sendEmail}
            onChange={(e) => setSendEmail(e.target.checked)}
            disabled={isRunning}
            className="rounded border-gray-300 text-teal-600 focus:ring-teal-500"
          />
          Send email
        </label>
      </div>
    </form>
  );
}
