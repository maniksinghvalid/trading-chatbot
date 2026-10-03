/** Sparkline.tsx — tiny line chart with an end dot; renders nothing under 2 points. */
import { extent, linePath, scale } from "@/lib/chart";

export default function Sparkline({
  values,
  color = "#ffb547",
  width = 120,
  height = 28,
  label,
}: {
  values: (number | null | undefined)[];
  color?: string;
  width?: number;
  height?: number;
  label: string;
}) {
  const nums = values.filter((v): v is number => typeof v === "number");
  if (nums.length < 2) return null;
  const [lo, hi] = extent(nums);
  const x = scale(0, values.length - 1, 2, width - 3);
  const y = scale(lo, hi, height - 3, 3);
  const lastIdx = values.map((v) => typeof v === "number").lastIndexOf(true);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}>
      <path
        d={linePath(values.map((v, i) => [x(i), typeof v === "number" ? y(v) : null]))}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(lastIdx)} cy={y(values[lastIdx] as number)} r="2.5" fill={color} />
    </svg>
  );
}
