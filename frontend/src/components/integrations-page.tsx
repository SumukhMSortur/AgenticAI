"use client";

import { useEffect, useState } from "react";
import { apiRequest, type IntegrationStatus } from "@/lib/api";
import { Card, PageTitle, StatusBadge } from "@/components/ui";

export function IntegrationsPage() {
  const [rows, setRows] = useState<IntegrationStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    apiRequest<IntegrationStatus[]>("/v1/integrations/status").then((result) => {
      if (active) setRows(result);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load integration status");
    });
    return () => { active = false; };
  }, []);
  return (
    <>
      <PageTitle title="Integration status" description="Data source freshness and connectivity. Unverified sources are not represented as live." />
      {error && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        {rows.map((row) => (
          <Card key={row.source}>
            <div className="flex items-start justify-between gap-3"><h2 className="font-semibold">{row.source}</h2><StatusBadge>{row.status}</StatusBadge></div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div><dt className="text-xs uppercase text-[#64736a]">Health</dt><dd className="mt-1"><StatusBadge>{row.health}</StatusBadge></dd></div>
              <div><dt className="text-xs uppercase text-[#64736a]">Live enabled</dt><dd className="mt-1">{row.live_enabled ? "Yes" : "No"}</dd></div>
              <div><dt className="text-xs uppercase text-[#64736a]">Records</dt><dd className="mt-1">{row.record_count}</dd></div>
              <div><dt className="text-xs uppercase text-[#64736a]">Snapshot age</dt><dd className="mt-1">{row.age_days === null ? "Unknown" : `${row.age_days} days`}</dd></div>
              <div className="col-span-2"><dt className="text-xs uppercase text-[#64736a]">As of</dt><dd className="mt-1">{row.as_of ? new Date(row.as_of).toLocaleString() : "Not available"}</dd></div>
            </dl>
          </Card>
        ))}
        {rows.length === 0 && !error && <Card><p className="text-sm text-[#64736a]">No integration status records are available.</p></Card>}
      </div>
    </>
  );
}
