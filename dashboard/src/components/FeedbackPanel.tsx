import { useCallback, useEffect, useState } from "react";

interface FeedbackData {
  user_action: string;
  final_price: number | null;
  satisfaction: number | null;
  price_accuracy: number | null;
  notes: string;
  reward: number | null;
}

interface Props {
  runId: string | null;
}

const ACTION_OPTIONS = [
  { value: "bought", label: "Bought at asking price", emoji: "💰" },
  { value: "negotiated", label: "Negotiated a deal", emoji: "🤝" },
  { value: "passed", label: "Passed on it", emoji: "👋" },
  { value: "still_looking", label: "Still deciding", emoji: "🔍" },
];

function StarRating({
  value,
  onChange,
  label,
}: {
  value: number | null;
  onChange: (v: number) => void;
  label: string;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label}
      </label>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onClick={() => onChange(star)}
            className={`w-8 h-8 rounded text-lg transition-colors ${
              value !== null && star <= value
                ? "bg-teal-100 text-teal-600"
                : "bg-gray-100 text-gray-300 hover:text-gray-400"
            }`}
          >
            ★
          </button>
        ))}
      </div>
    </div>
  );
}

export function FeedbackPanel({ runId }: Props) {
  const [existing, setExisting] = useState<FeedbackData | null>(null);
  const [action, setAction] = useState("");
  const [finalPrice, setFinalPrice] = useState("");
  const [satisfaction, setSatisfaction] = useState<number | null>(null);
  const [priceAccuracy, setPriceAccuracy] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load existing feedback for this run
  useEffect(() => {
    if (!runId) {
      setExisting(null);
      setSubmitted(false);
      return;
    }
    setLoading(true);
    fetch(`/api/runs/${runId}/feedback`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setExisting(data);
          setAction(data.user_action || "");
          setFinalPrice(data.final_price?.toString() || "");
          setSatisfaction(data.satisfaction);
          setPriceAccuracy(data.price_accuracy);
          setNotes(data.notes || "");
          setSubmitted(true);
        } else {
          setExisting(null);
          setAction("");
          setFinalPrice("");
          setSatisfaction(null);
          setPriceAccuracy(null);
          setNotes("");
          setSubmitted(false);
        }
      })
      .catch(() => setExisting(null))
      .finally(() => setLoading(false));
  }, [runId]);

  const handleSubmit = useCallback(async () => {
    if (!runId || !action) return;
    setSubmitting(true);
    try {
      const res = await fetch(`/api/runs/${runId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_action: action,
          final_price: finalPrice ? parseFloat(finalPrice) : null,
          satisfaction,
          price_accuracy: priceAccuracy,
          notes,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setExisting(data);
        setSubmitted(true);
      }
    } catch {
      // ignore
    } finally {
      setSubmitting(false);
    }
  }, [runId, action, finalPrice, satisfaction, priceAccuracy, notes]);

  if (!runId) {
    return (
      <div className="text-sm text-gray-400 italic py-4 text-center">
        Select a completed run to provide feedback
      </div>
    );
  }

  if (loading) {
    return (
      <div className="text-sm text-gray-400 italic py-4 text-center">
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Outcome Feedback
        </h3>
        {submitted && existing?.reward !== null && existing?.reward !== undefined && (
          <span
            className={`text-xs font-bold px-2 py-0.5 rounded ${
              existing.reward > 0.3
                ? "bg-green-100 text-green-700"
                : existing.reward < -0.3
                ? "bg-red-100 text-red-700"
                : "bg-gray-100 text-gray-600"
            }`}
          >
            Reward: {existing.reward > 0 ? "+" : ""}
            {existing.reward.toFixed(2)}
          </span>
        )}
      </div>

      {submitted && (
        <div className="bg-teal-50 border border-teal-200 rounded-lg p-3 text-sm text-teal-700">
          Feedback recorded. You can update it anytime.
        </div>
      )}

      {/* What happened? */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-2">
          What did you do?
        </label>
        <div className="grid grid-cols-2 gap-2">
          {ACTION_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setAction(opt.value)}
              className={`px-3 py-2 text-sm rounded-lg border transition-colors text-left ${
                action === opt.value
                  ? "bg-teal-50 border-teal-300 text-teal-700"
                  : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              {opt.emoji} {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Final price (if bought/negotiated) */}
      {(action === "bought" || action === "negotiated") && (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Final price paid
          </label>
          <div className="relative">
            <span className="absolute left-3 top-2 text-gray-400">$</span>
            <input
              type="number"
              value={finalPrice}
              onChange={(e) => setFinalPrice(e.target.value)}
              placeholder="0"
              className="w-full pl-7 pr-3 py-2 border border-gray-300 rounded-lg text-sm
                         focus:outline-none focus:ring-2 focus:ring-teal-500"
            />
          </div>
        </div>
      )}

      {/* Ratings */}
      <div className="grid grid-cols-2 gap-4">
        <StarRating
          value={satisfaction}
          onChange={setSatisfaction}
          label="Overall satisfaction"
        />
        <StarRating
          value={priceAccuracy}
          onChange={setPriceAccuracy}
          label="Price estimate accuracy"
        />
      </div>

      {/* Notes */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="Anything the agent missed, got wrong, etc."
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm
                     focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"
        />
      </div>

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={!action || submitting}
        className="w-full px-4 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg
                   hover:bg-teal-700 disabled:bg-gray-300 disabled:cursor-not-allowed
                   transition-colors"
      >
        {submitting
          ? "Saving..."
          : submitted
          ? "Update Feedback"
          : "Submit Feedback"}
      </button>
    </div>
  );
}
