"use client";

import { useEffect, useState } from "react";
import { apiRequest, type Factory, type FactoryRisk } from "@/lib/api";
import { Card, PageTitle, StatusBadge } from "@/components/ui";
import { RiskGauge } from "@/components/risk-gauge";

export function FactoriesPage() {
  const [factories, setFactories] = useState<Factory[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [risk, setRisk] = useState<FactoryRisk | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    apiRequest<Factory[]>("/v1/factories").then((rows) => {
      if (active) {
        setFactories(rows);
        if (rows[0]) setSelected(rows[0].id);
      }
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load factories");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    apiRequest<FactoryRisk>(`/v1/factories/${encodeURIComponent(selected)}/risk`).then((row) => {
      if (active) setRisk(row);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load factory risk");
    });
    return () => { active = false; };
  }, [selected]);

  const displayedRisk = risk?.factory_id === selected ? risk : null;
  return (
    <>
      <PageTitle title="Factory risk" description="Review forecasted six-month audit failure probability and model context." />
      {error && <p role="alert" className="mb-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">{error}</p>}
      <Card>
        <label className="block max-w-md text-sm font-medium">
          Factory
          <select value={selected} onChange={(event) => setSelected(event.target.value)} className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] bg-white px-3">
            {factories.map((factory) => <option key={factory.id} value={factory.id}>{factory.name} · {factory.country}</option>)}
          </select>
        </label>
      </Card>
      {factories.length === 0 && !error && <Card className="mt-5"><p className="text-sm text-[#64736a]">No factory records are available.</p></Card>}
      {displayedRisk && (
        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_2fr]">
          <Card className="flex flex-col items-center justify-center">
            <h2 className="self-start font-semibold">Estimated risk</h2>
            <RiskGauge score={displayedRisk.risk_score} />
          </Card>
          <Card>
            <h2 className="font-semibold">Forecast details</h2>
            <dl className="mt-4 grid gap-4 sm:grid-cols-2">
              <div><dt className="text-xs uppercase text-[#64736a]">Model</dt><dd className="mt-1"><StatusBadge>{displayedRisk.model_tag}</StatusBadge></dd></div>
              <div><dt className="text-xs uppercase text-[#64736a]">Last updated</dt><dd className="mt-1 text-sm">{new Date(displayedRisk.created_at).toLocaleString()}</dd></div>
              <div><dt className="text-xs uppercase text-[#64736a]">Related assessment</dt><dd className="mt-1 break-all text-sm">{displayedRisk.job_id}</dd></div>
            </dl>
            <h3 className="mt-6 font-semibold">Baseline comparison</h3>
            <pre className="mt-2 overflow-auto rounded-lg bg-[#f7f9f7] p-3 text-xs">{JSON.stringify(displayedRisk.baseline_comparison, null, 2)}</pre>
          </Card>
        </div>
      )}
    </>
  );
}
