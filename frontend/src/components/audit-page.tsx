"use client";

import { useEffect, useState } from "react";
import { apiRequest, type AuditEvent } from "@/lib/api";
import { Card, PageTitle } from "@/components/ui";

export function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    apiRequest<AuditEvent[]>("/v1/audit-events").then((rows) => {
      if (active) setEvents(rows);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load audit events");
    });
    return () => { active = false; };
  }, []);
  return (
    <>
      <PageTitle title="Audit trail" description="Append-only event history with sequence and hash-chain verification metadata." />
      {error && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      <Card className="overflow-hidden p-0">
        {events.length === 0 ? <p className="p-5 text-sm text-[#64736a]">No audit events are available.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-left text-sm">
              <thead className="bg-[#f7f9f7] text-xs uppercase text-[#64736a]"><tr><th className="px-5 py-3">Sequence</th><th className="px-5 py-3">Event</th><th className="px-5 py-3">Timestamp</th><th className="px-5 py-3">Previous hash</th><th className="px-5 py-3">Event hash</th></tr></thead>
              <tbody>{events.map((event) => <tr key={event.id} className="border-t border-[#edf1ed]"><td className="px-5 py-4 font-mono">{event.sequence}</td><td className="px-5 py-4 font-semibold">{event.event_type}</td><td className="px-5 py-4">{new Date(event.timestamp).toLocaleString()}</td><td className="max-w-52 truncate px-5 py-4 font-mono text-xs" title={event.prev_hash}>{event.prev_hash}</td><td className="max-w-52 truncate px-5 py-4 font-mono text-xs" title={event.event_hash}>{event.event_hash}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
