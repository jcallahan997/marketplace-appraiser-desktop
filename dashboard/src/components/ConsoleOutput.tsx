import { useEffect, useRef } from "react";

interface Props {
  logs: string[];
}

export function ConsoleOutput({ logs }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new logs appear
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    // Only auto-scroll if user is near the bottom
    const isNearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 80;
    if (isNearBottom) {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Console Output
      </h3>
      <div
        ref={containerRef}
        className="flex-1 bg-[#1a1a2e] rounded-lg p-3 overflow-y-auto console-scroll font-mono text-xs leading-relaxed min-h-0"
      >
        {logs.length === 0 ? (
          <p className="text-gray-500 italic">
            Waiting for pipeline to start...
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
    </div>
  );
}
