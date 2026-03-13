import { useCallback, useEffect, useState } from "react";
import type { RunSummary } from "../types";

const API = "/api";

export interface UseAppraisalReturn {
  startAppraisal: (url: string, sendEmail: boolean) => Promise<string | null>;
  runs: RunSummary[];
  refreshRuns: () => Promise<void>;
  sendEmail: (runId: string) => Promise<boolean>;
  loading: boolean;
  error: string | null;
}

export function useAppraisal(): UseAppraisalReturn {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshRuns = useCallback(async () => {
    try {
      const res = await fetch(`${API}/runs`);
      if (res.ok) {
        const data = await res.json();
        setRuns(data);
      }
    } catch {
      // silently fail — will retry
    }
  }, []);

  const startAppraisal = useCallback(
    async (listingUrl: string, sendEmail: boolean): Promise<string | null> => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API}/appraise`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            listing_url: listingUrl,
            send_email: sendEmail,
          }),
        });
        if (!res.ok) {
          const data = await res.json();
          setError(data.detail || "Failed to start appraisal");
          return null;
        }
        const data = await res.json();
        return data.run_id;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Network error");
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const sendEmail = useCallback(async (runId: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API}/runs/${runId}/send`, { method: "POST" });
      return res.ok;
    } catch {
      return false;
    }
  }, []);

  // Load runs on mount
  useEffect(() => {
    refreshRuns();
  }, [refreshRuns]);

  return { startAppraisal, runs, refreshRuns, sendEmail, loading, error };
}
