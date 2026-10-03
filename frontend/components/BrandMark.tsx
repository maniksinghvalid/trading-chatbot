/**
 * BrandMark.tsx — "Night Desk" logo: three candlesticks rising out of a frame.
 * Decorative only (aria-hidden); pair it with visible text. Solid fills on
 * purpose: a gradient id would collide when two marks render (one hidden).
 */
export default function BrandMark({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 36 36" className={className} aria-hidden="true">
      <rect x="1" y="1" width="34" height="34" rx="9" fill="#10131a" stroke="#2a3142" />
      <g stroke="#c9821c" strokeWidth="1.5" strokeLinecap="round">
        <line x1="11" y1="15" x2="11" y2="28" />
        <line x1="18" y1="10" x2="18" y2="25" />
        <line x1="25" y1="6" x2="25" y2="20" />
      </g>
      <g fill="#ffb547">
        <rect x="8.5" y="18" width="5" height="7" rx="1.2" />
        <rect x="15.5" y="13" width="5" height="8" rx="1.2" />
        <rect x="22.5" y="8.5" width="5" height="8" rx="1.2" />
      </g>
    </svg>
  );
}
