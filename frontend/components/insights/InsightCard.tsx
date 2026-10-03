/**
 * InsightCard.tsx — shared frame for insight visuals: title, body, provenance footer.
 * Report text is rendered as JSX text only (T-06-01).
 */
import type { ReactNode } from "react";
import type { InsightSource } from "@/lib/types";

export default function InsightCard({
  title,
  source,
  className = "",
  children,
}: {
  title: string;
  source?: InsightSource;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`min-w-0 rounded-2xl border border-ink-700 bg-ink-900/70 p-4 ${className}`}>
      <h4 className="mb-3 font-mono text-[10px] uppercase tracking-[0.2em] text-paper-dim">{title}</h4>
      {children}
      {source && (
        <p
          className="mt-3 truncate border-t border-ink-700/70 pt-2 font-mono text-[10px] text-paper-mute"
          title={source.source_path}
        >
          From {source.source_path} · {source.generated_date}
        </p>
      )}
    </section>
  );
}
