"use client";

/**
 * CitationCard.tsx — expandable citation card component.
 *
 * Renders a citation collapsed (source_path • report_type • generated_date)
 * with an expand toggle that reveals the chunk text when present.
 *
 * Replaces the inline Sources list in MessageBubble.
 *
 * Security (T-06-01): No raw HTML rendered; all content is plain text in JSX.
 * No rehype-raw, no dangerouslySetInnerHTML.
 */

import { useState } from "react";
import type { Citation } from "@/lib/types";

/** Report-type accent colours (full class strings so Tailwind keeps them). */
const TYPE_STYLES: Record<string, string> = {
  ANALYSIS: "text-amber-glow border-amber-glow/30 bg-amber-glow/10",
  OPTIONS: "text-[#b9a4ff] border-[#b9a4ff]/30 bg-[#b9a4ff]/10",
  TECHNICAL: "text-[#5fd4ea] border-[#5fd4ea]/30 bg-[#5fd4ea]/10",
  FUNDAMENTAL: "text-gain border-gain/30 bg-gain/10",
  SENTIMENT: "text-[#ff9ccf] border-[#ff9ccf]/30 bg-[#ff9ccf]/10",
  RISK: "text-loss border-loss/30 bg-loss/10",
};
const DEFAULT_TYPE_STYLE = "text-paper-dim border-ink-600 bg-ink-800";

interface CitationCardProps {
  citation: Citation;
  index: number;
}

export default function CitationCard({ citation, index }: CitationCardProps) {
  const [expanded, setExpanded] = useState(false);

  // chunk_text is an optional field that the backend may include in Citation.
  // Cast to any to safely access it without requiring a types.ts migration.
  const chunkText = (citation as unknown as Record<string, unknown>).chunk_text as string | undefined;
  const type = (citation.report_type || "").toUpperCase();
  const name = citation.source_path.split("/").pop()?.replace(/\.md$/i, "") ?? citation.source_path;

  return (
    <div
      className={`overflow-hidden rounded-xl border border-ink-700 bg-ink-900/70 transition hover:border-ink-600 ${
        expanded ? "sm:col-span-2" : ""
      }`}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        disabled={!chunkText}
        className={`flex w-full items-center gap-3 px-3 py-2.5 text-left ${
          chunkText ? "cursor-pointer hover:bg-ink-850" : "cursor-default"
        }`}
        aria-expanded={expanded}
        title={citation.source_path}
      >
        {/* Index — matches the [n] markers in the answer text */}
        <span className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-md border border-ink-700 bg-ink-850 font-mono text-[11px] text-paper-dim">
          {index + 1}
        </span>

        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-[11px] text-paper">{name}</span>
          <span className="mt-1 flex items-center gap-2">
            <span
              className={`rounded border px-1.5 py-px font-mono text-[9px] font-semibold uppercase tracking-wider ${
                TYPE_STYLES[type] ?? DEFAULT_TYPE_STYLE
              }`}
            >
              {type || "REPORT"}
            </span>
            <span className="font-mono text-[10px] text-paper-mute">{citation.generated_date}</span>
          </span>
        </span>

        {chunkText && (
          <span
            className={`flex-shrink-0 text-paper-mute transition-transform ${expanded ? "rotate-180" : ""}`}
            aria-hidden="true"
          >
            ▾
          </span>
        )}
      </button>

      {expanded && chunkText && (
        <div className="border-t border-ink-700 px-4 pb-4 pt-3">
          <p className="whitespace-pre-wrap border-l-2 border-amber-glow/40 pl-3 text-xs leading-relaxed text-paper-dim">
            {chunkText}
          </p>
        </div>
      )}
    </div>
  );
}
