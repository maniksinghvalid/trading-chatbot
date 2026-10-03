/**
 * InsightsPanel.tsx — lays out whichever insight sections the backend sent.
 * Missing sections render nothing; full-width cards span both columns.
 */
import type { Insights } from "@/lib/types";
import ExpectedMoveCard from "./ExpectedMoveCard";
import IvCard from "./IvCard";
import KeyLevelsCard from "./KeyLevelsCard";
import PayoffCard from "./PayoffCard";
import ScoreCard from "./ScoreCard";
import TrendCard from "./TrendCard";

export default function InsightsPanel({ insights }: { insights: Insights }) {
  const { score, trend, iv, expected_move, key_levels, strategy } = insights;
  const pair = key_levels && iv;
  return (
    <div className="animate-rise mb-5 grid gap-3 sm:grid-cols-2">
      {score && <ScoreCard score={score} trend={trend} className="sm:col-span-2" />}
      {trend?.focus && <TrendCard trend={trend} className="sm:col-span-2" />}
      {expected_move && <ExpectedMoveCard data={expected_move} className="sm:col-span-2" />}
      {strategy && <PayoffCard data={strategy} className="sm:col-span-2" />}
      {key_levels && <KeyLevelsCard data={key_levels} className={pair ? "" : "sm:col-span-2"} />}
      {iv && <IvCard iv={iv} trend={trend} className={pair ? "" : "sm:col-span-2"} />}
    </div>
  );
}
