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

interface CitationCardProps {
  citation: Citation;
  index: number;
}

export default function CitationCard({ citation, index }: CitationCardProps) {
  const [expanded, setExpanded] = useState(false);

  // chunk_text is an optional field that the backend may include in Citation.
  // Cast to any to safely access it without requiring a types.ts migration.
  const chunkText = (citation as unknown as Record<string, unknown>).chunk_text as string | undefined;

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900 text-xs overflow-hidden">
      {/* Collapsed header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        disabled={!chunkText}
        className={`w-full flex items-start gap-2 px-3 py-2 text-left transition-colors
          ${chunkText ? "hover:bg-gray-800 cursor-pointer" : "cursor-default"}`}
        aria-expanded={expanded}
      >
        {/* Citation index badge */}
        <span className="flex-shrink-0 font-mono text-gray-500">[{index + 1}]</span>

        {/* Source path */}
        <span className="flex-1 truncate text-gray-300">{citation.source_path}</span>

        {/* Metadata pills */}
        <span className="flex-shrink-0 text-blue-400">{citation.report_type}</span>
        <span className="flex-shrink-0 text-gray-600 hidden sm:inline">&bull;</span>
        <span className="flex-shrink-0 text-gray-500">{citation.generated_date}</span>

        {/* Expand chevron (only shown when chunk text is available) */}
        {chunkText && (
          <span
            className={`flex-shrink-0 text-gray-500 transition-transform ${expanded ? "rotate-180" : ""}`}
            aria-hidden="true"
          >
            ▾
          </span>
        )}
      </button>

      {/* Expanded chunk text */}
      {expanded && chunkText && (
        <div className="px-3 pb-3 pt-1 border-t border-gray-700">
          <p className="text-gray-400 leading-relaxed whitespace-pre-wrap">{chunkText}</p>
        </div>
      )}
    </div>
  );
}
