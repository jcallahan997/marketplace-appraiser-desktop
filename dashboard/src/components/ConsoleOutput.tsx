import { useEffect, useRef, useState } from "react";

interface Props {
  logs: string[];
}

export function ConsoleOutput({ logs }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const [hasNewLogs, setHasNewLogs] = useState(false);

  // Track scroll position to detect user scrolling away from bottom
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const handleScroll = () => {
      const isNearBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 200;
      setPinnedToBottom(isNearBottom);
      if (isNearBottom) setHasNewLogs(false);
    };
    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  // Auto-scroll to bottom when new logs appear (only if pinned)
  useEffect(() => {
    if (pinnedToBottom) {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    } else if (logs.length > 0) {
      setHasNewLogs(true);
    }
  }, [logs, pinnedToBottom]);

  const scrollToBottom = () => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
    setPinnedToBottom(true);
    setHasNewLogs(false);
  };

  return (
    <div className="flex flex-col h-full relative">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Console Output
      </h3>
      <div
        ref={containerRef}
        className="flex-1 bg-[#1a1a2e] rounded-lg p-3 overflow-y-auto console-scroll font-mono text-xs leading-relaxed min-h-0"
      >
        {logs.length === 0 ? (
          <p className="text-gray-500 italic">
            Paste a listing URL above and click Start Appraisal to see live output.
          </p>
        ) : (
          logs.map((line, i) => (
            <div
              key={i}
              className={
                line.startsWith("STEP ")
                  ? "text-teal-400 font-bold mt-2"
                  : line.startsWith("  Error") || line.startsWith("  Warning")
                  ? "text-red-400"
                  : line.startsWith("===")
                  ? "text-gray-500"
                  : "text-gray-300"
              }
            >
              {line}
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>

      {/* Scroll-to-bottom button */}
      {!pinnedToBottom && logs.length > 0 && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-4 right-6 px-3 py-1.5 bg-teal-600 text-white text-xs font-medium rounded-full shadow-lg hover:bg-teal-700 transition-colors flex items-center gap-1"
        >
          <span>↓</span>
          {hasNewLogs && <span>New logs</span>}
        </button>
      )}
    </div>
  );
}
