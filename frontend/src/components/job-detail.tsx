"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { apiImageUrl, apiRequest, type DocumentRecord, type Job, type Scorecard } from "@/lib/api";
import { bboxToPercent } from "@/lib/geometry";
import { scorecardLines, type VerifiedLine } from "@/lib/scorecard";
import { attachJobEventHandlers } from "@/lib/job-events";
import { Button, Card, PageTitle, StatusBadge } from "@/components/ui";

interface JobDetailProps {
  jobId: string;
}

type TimelineStepStatus = "waiting" | "running" | "done" | "needs_review" | "failed";

interface TimelineStep {
  id: string;
  label: string;
  description: string;
  status: TimelineStepStatus;
}

const INITIAL_STEPS: TimelineStep[] = [
  { id: "redact", label: "Redact", description: "Hides PII and sensitive identifiers locally", status: "waiting" },
  { id: "extract", label: "Extract", description: "Extracts structured certificate metadata and claims", status: "waiting" },
  { id: "forecast", label: "Forecast risk", description: "Predicts 6-month factory audit failure risk", status: "waiting" },
  { id: "retrieve", label: "Find law", description: "Retrieves applicable environmental regulation citations", status: "waiting" },
  { id: "verify", label: "Verify", description: "Runs deterministic rule-based checks on claims", status: "waiting" },
  { id: "decide", label: "Decide", description: "Produces final compliance scorecard or escalates", status: "waiting" },
];

export function JobDetail({ jobId }: JobDetailProps) {
  const [job, setJob] = useState<Job | null>(null);
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [steps, setSteps] = useState<TimelineStep[]>(INITIAL_STEPS);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<VerifiedLine | null>(null);
  const [page, setPage] = useState(1);
  const [actionNotes, setActionNotes] = useState<Record<string, string>>({});
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      apiRequest<Job>(`/v1/jobs/${encodeURIComponent(jobId)}`),
      apiRequest<DocumentRecord[]>(`/v1/jobs/${encodeURIComponent(jobId)}/documents`),
    ])
      .then(([jobData, docData]) => {
        if (active) {
          setJob(jobData);
          setDocuments(docData);
          updateStepsFromJobStatus(jobData.status);
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load this job");
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  function updateStepsFromJobStatus(status: string) {
    if (status === "completed") {
      setSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
    } else if (status === "review_required") {
      setSteps((prev) =>
        prev.map((s) => (s.id === "decide" ? { ...s, status: "needs_review" } : { ...s, status: "done" }))
      );
    } else if (status === "failed") {
      setSteps((prev) =>
        prev.map((s, idx) => (idx === 0 ? { ...s, status: "failed" } : { ...s, status: "waiting" }))
      );
    }
  }

  useEffect(() => {
    const source = new EventSource(`/api/backend/v1/jobs/${encodeURIComponent(jobId)}/events`);
    return attachJobEventHandlers(
      source,
      (data) => {
        setEvents((current) => [...current.slice(-29), data]);
        // Update timeline steps based on incoming event data
        try {
          const parsedEvent = typeof data === "string" ? JSON.parse(data) : data;
          const stepKey = parsedEvent.step || parsedEvent.event_type;
          if (stepKey) {
            setSteps((prev) =>
              prev.map((s) => {
                if (s.id === stepKey || s.id.includes(stepKey)) {
                  return { ...s, status: "done" };
                }
                return s;
              })
            );
          }
          if (parsedEvent.event_type === "review_required") {
            setSteps((prev) =>
              prev.map((s) => (s.id === "decide" ? { ...s, status: "needs_review" } : s))
            );
          } else if (parsedEvent.event_type === "completed") {
            setSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
          }
        } catch {
          // Plain string event fallback
        }
      },
      () => setEvents((current) => [...current.slice(-29), "Connection interrupted; reconnecting…"])
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

  async function handleEscalationDecision(decision: "approved" | "rejected") {
    setActionInProgress(decision);
    setError(null);
    try {
      // Find pending review for this job
      const reviews = await apiRequest<Array<{ id: string; job_id: string }>>("/v1/reviews");
      const currentReview = reviews.find((r) => r.job_id === jobId);
      if (currentReview) {
        await apiRequest(`/v1/reviews/${encodeURIComponent(currentReview.id)}/decision`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, notes: actionNotes[jobId] || "Decision via scorecard" }),
        });
        // Reload job status
        const updated = await apiRequest<Job>(`/v1/jobs/${encodeURIComponent(jobId)}`);
        setJob(updated);
        updateStepsFromJobStatus(updated.status);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to record decision");
    } finally {
      setActionInProgress(null);
    }
  }

  const parsed = scorecard ? scorecardLines(scorecard) : { lines: [], omittedCount: 0 };
  const selectedDoc = selected ? documents.find((doc) => doc.id === selected.claim.doc_id) : undefined;
  const box = selected?.claim.bbox ? bboxToPercent(selected.claim.bbox) : null;

  return (
    <>
      <PageTitle
        title={job ? `Assessment ${job.id}` : "Assessment details"}
        description="Live processing workflow, evidence-linked findings, and verified legal citations."
        action={
          <Link href="/jobs" className="text-sm font-semibold text-[#176b4a] hover:underline">
            ← All jobs
          </Link>
        }
      />

      {error && (
        <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">
          {error}
        </p>
      )}

      {/* Top summary cards */}
      {job && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Card>
            <p className="text-xs uppercase tracking-wider text-[#64736a]">Overall Status</p>
            <div className="mt-2">
              <StatusBadge>{job.status}</StatusBadge>
            </div>
          </Card>
          <Card>
            <p className="text-xs uppercase tracking-wider text-[#64736a]">Assessment Date</p>
            <p className="mt-2 text-base font-semibold">{job.assessment_date}</p>
          </Card>
          <Card>
            <p className="text-xs uppercase tracking-wider text-[#64736a]">6-Month Failure Risk</p>
            <div className="mt-2 flex items-center gap-2">
              <div className="h-2.5 w-full max-w-[120px] rounded-full bg-[#e5ece6]">
                <div
                  className={`h-2.5 rounded-full ${
                    (job.risk_score || 0) > 0.5 ? "bg-red-500" : "bg-[#176b4a]"
                  }`}
                  style={{ width: `${Math.round((job.risk_score || 0) * 100)}%` }}
                />
              </div>
              <span className="font-semibold text-sm">
                {job.risk_score !== null ? `${Math.round(job.risk_score * 100)}%` : "Pending"}
              </span>
            </div>
          </Card>
        </div>
      )}

      {/* Live Timeline Section */}
      <Card className="mt-6">
        <h2 className="text-base font-semibold">Workflow steps (Live progress)</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {steps.map((step, idx) => (
            <div
              key={step.id}
              className={`rounded-xl border p-3 transition ${
                step.status === "done"
                  ? "border-[#176b4a] bg-[#eaf4ed]"
                  : step.status === "needs_review"
                  ? "border-amber-400 bg-amber-50"
                  : step.status === "failed"
                  ? "border-red-400 bg-red-50"
                  : "border-[#dce5dd] bg-white opacity-70"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[#64736a]">0{idx + 1}</span>
                <span
                  className={`inline-block size-2 rounded-full ${
                    step.status === "done"
                      ? "bg-[#176b4a]"
                      : step.status === "needs_review"
                      ? "bg-amber-500"
                      : step.status === "failed"
                      ? "bg-red-500"
                      : "bg-[#cbd8cf]"
                  }`}
                />
              </div>
              <p className="mt-1 font-semibold text-sm text-[#1b2b22]">{step.label}</p>
              <p className="mt-1 text-xs text-[#64736a]">{step.description}</p>
            </div>
          ))}
        </div>
      </Card>

      {/* Scorecard Table & Escalation Decisions */}
      {scorecard && (
        <Card className="mt-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Compliance scorecard</h2>
              <p className="mt-1 text-sm text-[#64736a]">{scorecard.summary}</p>
            </div>
            <StatusBadge>{scorecard.overall_status}</StatusBadge>
          </div>

          {job?.status === "review_required" && (
            <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
              <h3 className="font-semibold text-sm text-amber-900">Human review required</h3>
              <p className="mt-1 text-xs text-amber-800">
                Deterministic verifier found uncertain or failing claims. Authorize or reject to resume the run.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  placeholder="Reviewer notes (optional)"
                  value={actionNotes[jobId] || ""}
                  onChange={(e) => setActionNotes({ ...actionNotes, [jobId]: e.target.value })}
                  className="min-h-9 flex-1 rounded-lg border border-amber-200 bg-white px-3 text-xs focus:outline-none"
                />
                <Button
                  disabled={actionInProgress !== null}
                  onClick={() => void handleEscalationDecision("approved")}
                >
                  Approve claim
                </Button>
                <Button
                  variant="danger"
                  disabled={actionInProgress !== null}
                  onClick={() => void handleEscalationDecision("rejected")}
                >
                  Reject claim
                </Button>
              </div>
            </div>
          )}

          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[700px] text-left text-sm">
              <thead className="bg-[#f7f9f7] text-xs uppercase text-[#64736a]">
                <tr>
                  <th className="px-4 py-3">Claim</th>
                  <th className="px-4 py-3">Verdict</th>
                  <th className="px-4 py-3">Rule / Code</th>
                  <th className="px-4 py-3">Source & Law</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {parsed.lines.map((line) => (
                  <tr key={line.claim.claim_id} className="border-t border-[#edf1ed] hover:bg-[#fafbfa]">
                    <td className="px-4 py-3 font-medium text-[#1b2b22]">{line.claim.claim_text}</td>
                    <td className="px-4 py-3">
                      <StatusBadge>{line.verdict.outcome}</StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-xs text-[#64736a]">
                      <div>{line.verdict.rule_id}</div>
                      <div className="text-[11px] text-[#819287]">{line.verdict.reason_code}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-[#64736a]">
                      <div>Doc: {line.claim.doc_id.slice(0, 8)}… p.{line.claim.page}</div>
                      <div className="text-[11px] text-[#176b4a]">ISO 14001:2015 §6.1.2</div>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => {
                          setSelected(line);
                          setPage(line.claim.page);
                        }}
                        className="rounded px-2.5 py-1 text-xs font-semibold text-[#176b4a] hover:bg-[#eaf4ed]"
                      >
                        Inspect PDF →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* PDF Inspection Viewer */}
      {selected && selectedDoc && (
        <Card className="mt-6">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-sm">
              Source document: {selectedDoc.filename} (Page {selected.claim.page})
            </h2>
            <button
              onClick={() => setSelected(null)}
              className="text-xs text-[#64736a] hover:text-[#1b2b22]"
            >
              Close viewer ✕
            </button>
          </div>
          <div className="relative mt-4 inline-block max-w-full overflow-hidden rounded-lg border border-[#dce5dd]">
            <Image
              src={apiImageUrl(selectedDoc.id, page)}
              alt={`${selectedDoc.filename}, page ${page}`}
              width={1000}
              height={1400}
              unoptimized
              className="block h-auto max-h-[70vh] max-w-full object-contain"
            />
            {box && selected.claim.page === page && (
              <span
                aria-label="Evidence location"
                className="pointer-events-none absolute border-2 border-red-600 bg-red-400/20"
                style={box}
              />
            )}
          </div>
        </Card>
      )}
    </>
  );
}
