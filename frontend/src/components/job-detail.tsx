"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { apiImageUrl, apiRequest, type DocumentRecord, type Job, type Scorecard } from "@/lib/api";
import { bboxToPercent } from "@/lib/geometry";
import { scorecardLines, type VerifiedLine } from "@/lib/scorecard";
import { attachJobEventHandlers } from "@/lib/job-events";
import { Card, PageTitle, StatusBadge } from "@/components/ui";

interface JobDetailProps {
  jobId: string;
}

export function JobDetail({ jobId }: JobDetailProps) {
  const [job, setJob] = useState<Job | null>(null);
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<VerifiedLine | null>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let active = true;
    Promise.all([
      apiRequest<Job>(`/v1/jobs/${encodeURIComponent(jobId)}`),
      apiRequest<DocumentRecord[]>(`/v1/jobs/${encodeURIComponent(jobId)}/documents`),
    ]).then(([jobData, docData]) => {
      if (active) {
        setJob(jobData);
        setDocuments(docData);
      }
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load this job");
    });
    return () => {
      active = false;
    };
  }, [jobId]);

  useEffect(() => {
    const source = new EventSource(`/api/backend/v1/jobs/${encodeURIComponent(jobId)}/events`);
    return attachJobEventHandlers(
      source,
      (data) => setEvents((current) => [...current.slice(-29), data]),
      () => setEvents((current) => [...current.slice(-29), "Connection interrupted; reconnecting…"]),
    );
  }, [jobId]);

  useEffect(() => {
    if (!job || !["completed", "review_required"].includes(job.status)) return;
    let active = true;
    apiRequest<Scorecard>(`/v1/jobs/${encodeURIComponent(jobId)}/scorecard`)
      .then((result) => {
        if (active) setScorecard(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load scorecard");
      });
    return () => {
      active = false;
    };
  }, [job, jobId]);

  const parsed = scorecard ? scorecardLines(scorecard) : { lines: [], omittedCount: 0 };
  const selectedDoc = selected ? documents.find((doc) => doc.id === selected.claim.doc_id) : undefined;
  const box = selected?.claim.bbox ? bboxToPercent(selected.claim.bbox) : null;

  return (
    <>
      <PageTitle
        title={job ? `Assessment ${job.id}` : "Assessment details"}
        description="Live processing updates, evidence-linked findings, and source document locations."
        action={<Link href="/jobs" className="text-sm font-semibold text-[#176b4a] hover:underline">← All jobs</Link>}
      />
      {error && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      {job && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card><p className="text-sm text-[#64736a]">Status</p><div className="mt-2"><StatusBadge>{job.status}</StatusBadge></div></Card>
          <Card><p className="text-sm text-[#64736a]">Assessment date</p><p className="mt-2 font-semibold">{job.assessment_date}</p></Card>
          <Card><p className="text-sm text-[#64736a]">Risk score</p><p className="mt-2 font-semibold">{job.risk_score === null ? "Pending" : `${Math.round(job.risk_score * 100)}%`}</p></Card>
        </div>
      )}
      <Card className="mt-5">
        <h2 className="font-semibold">Processing events</h2>
        {events.length ? <ol aria-live="polite" className="mt-3 space-y-2 text-sm text-[#64736a]">{events.map((event, index) => <li key={`${index}-${event}`}>{event}</li>)}</ol> : <p className="mt-2 text-sm text-[#64736a]">Waiting for job events…</p>}
      </Card>
      {scorecard && (
        <>
          <Card className="mt-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="text-lg font-semibold">Evidence scorecard</h2><p className="mt-1 max-w-3xl text-sm text-[#64736a]">{scorecard.summary}</p></div>
              <StatusBadge>{scorecard.overall_status}</StatusBadge>
            </div>
            {parsed.omittedCount > 0 && <p role="status" className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{parsed.omittedCount} item(s) were withheld because verifiable evidence IDs were missing or the record was invalid.</p>}
            <div className="mt-4 grid gap-3">
              {parsed.lines.map((line) => (
                <button
                  type="button"
                  key={line.claim.claim_id}
                  onClick={() => { setSelected(line); setPage(line.claim.page); }}
                  className="rounded-xl border border-[#dce5dd] p-4 text-left hover:border-[#176b4a] hover:bg-[#f8fbf8]"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{line.claim.claim_text}</h3><StatusBadge>{line.verdict.outcome}</StatusBadge></div>
                  <p className="mt-2 text-xs text-[#64736a]">Rule {line.verdict.rule_id} · {line.verdict.reason_code} · Evidence: {line.claim.evidence_ids.join(", ")}</p>
                </button>
              ))}
              {parsed.lines.length === 0 && <p className="text-sm text-[#64736a]">No evidence-verified scorecard lines are available.</p>}
            </div>
          </Card>
          {selected && (
            <Card className="mt-5">
              <div className="flex items-center justify-between gap-3">
                <div><h2 className="font-semibold">Source evidence</h2><p className="mt-1 text-sm text-[#64736a]">{selectedDoc?.filename ?? selected.claim.doc_id} · page {selected.claim.page}</p></div>
                {selectedDoc && <span className="text-xs text-[#64736a]">SHA-256 {selected.claim.doc_hash}</span>}
              </div>
              {selectedDoc ? (
                <div className="relative mt-4 inline-block max-w-full overflow-hidden rounded-lg border border-[#dce5dd]">
                  <Image
                    src={apiImageUrl(selectedDoc.id, page)}
                    alt={`${selectedDoc.filename}, page ${page}`}
                    width={1000}
                    height={1400}
                    unoptimized
                    className="block h-auto max-h-[75vh] max-w-full object-contain"
                  />
                  {box && selected.claim.page === page && <span aria-label="Evidence location" className="pointer-events-none absolute border-2 border-red-600 bg-red-400/15" style={box} />}
                  {selected.claim.bbox === null && <span className="absolute left-2 top-2 rounded bg-white/90 px-2 py-1 text-xs">No source bounding box recorded</span>}
                </div>
              ) : <p className="mt-4 text-sm text-[#64736a]">Source document metadata is unavailable for this evidence reference.</p>}
              {selectedDoc && selectedDoc.page_count > 1 && <div className="mt-3 flex items-center gap-3"><button className="rounded border px-3 py-1" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous page</button><span className="text-sm">Page {page} / {selectedDoc.page_count}</span><button className="rounded border px-3 py-1" disabled={page >= selectedDoc.page_count} onClick={() => setPage((value) => value + 1)}>Next page</button></div>}
            </Card>
          )}
        </>
      )}
    </>
  );
}
