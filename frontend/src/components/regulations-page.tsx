"use client";

import { useEffect, useState } from "react";
import { apiRequest, type RegulationProposal } from "@/lib/api";
import { Button, Card, PageTitle, StatusBadge } from "@/components/ui";

export function RegulationsPage() {
  const [proposals, setProposals] = useState<RegulationProposal[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    setProposals(await apiRequest<RegulationProposal[]>("/v1/regulation-proposals"));
  }
  useEffect(() => {
    let active = true;
    apiRequest<RegulationProposal[]>("/v1/regulation-proposals").then((rows) => {
      if (active) setProposals(rows);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load regulation proposals");
    });
    return () => { active = false; };
  }, []);

  async function decide(proposal: RegulationProposal, decision: "approved" | "rejected") {
    setBusy(proposal.id);
    setError(null);
    try {
      await apiRequest<RegulationProposal>(`/v1/regulation-proposals/${encodeURIComponent(proposal.id)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, notes: notes[proposal.id] ?? "" }),
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to record proposal decision");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageTitle title="Regulation updates" description="Review and explicitly approve or reject proposed regulation snapshots." />
      {error && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      <div className="space-y-4">
        {proposals.length === 0 && <Card><p className="text-sm text-[#64736a]">No pending proposals.</p></Card>}
        {proposals.map((proposal) => (
          <Card key={proposal.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="font-semibold">{proposal.source}</h2><p className="mt-1 break-all text-sm text-[#64736a]">Candidate version {proposal.candidate_version_id}</p><p className="mt-1 text-xs text-[#64736a]">Detected {new Date(proposal.detected_at).toLocaleString()}</p></div>
              <StatusBadge>{proposal.status}</StatusBadge>
            </div>
            {proposal.status === "pending" && <>
              <label className="mt-4 block text-sm font-medium">Decision notes<textarea value={notes[proposal.id] ?? ""} onChange={(event) => setNotes((current) => ({ ...current, [proposal.id]: event.target.value }))} maxLength={4000} rows={3} className="mt-1.5 w-full rounded-lg border border-[#cbd8cf] p-3" /></label>
              <div className="mt-3 flex gap-2"><Button disabled={busy === proposal.id} onClick={() => void decide(proposal, "approved")}>Approve & ingest</Button><Button variant="danger" disabled={busy === proposal.id} onClick={() => void decide(proposal, "rejected")}>Reject</Button></div>
              <p className="mt-3 text-xs text-[#64736a]">Approval performs the backend&apos;s regulation ingestion workflow; review source and version details before confirming.</p>
            </>}
          </Card>
        ))}
      </div>
    </>
  );
}
