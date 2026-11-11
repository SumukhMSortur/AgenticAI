import { riskScorePercent } from "@/lib/risk";

export function RiskGauge({ score }: { score: number }) {
  const percent = riskScorePercent(score);
  const color = percent >= 70 ? "#b83232" : percent >= 40 ? "#c58116" : "#21805b";
  return (
    <div
      role="meter"
      aria-label="Six-month audit failure risk"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      className="relative mt-6 grid size-56 place-items-center rounded-full"
      style={{ background: `conic-gradient(${color} ${percent * 3.6}deg, #e8eee9 0deg)` }}
    >
      <div className="grid size-44 place-content-center rounded-full bg-white text-center">
        <span className="text-4xl font-semibold">{percent}%</span>
        <span className="text-xs text-[#64736a]">next six months</span>
      </div>
    </div>
  );
}
