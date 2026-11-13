"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiRequest, type DocumentRecord, type Job } from "@/lib/api";
import { Button, Card, PageTitle, StatusBadge } from "@/components/ui";

const SAMPLE_FILES = [
  { name: "valid_cert.pdf", label: "Valid certificate (Approved)" },
  { name: "expired_cert.pdf", label: "Expired certificate (Failed)" },
  { name: "unknown_issuer.pdf", label: "Unknown issuer (Needs review)" },
  { name: "scope_mismatch.pdf", label: "Scope mismatch (Needs review)" },
];

export function JobsPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadJobs() {
    const result = await apiRequest<Job[]>("/v1/jobs");
    setJobs(result);
  }

  useEffect(() => {
    let active = true;
    apiRequest<Job[]>("/v1/jobs")
      .then((result) => {
        if (active) setJobs(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load assessments");
      });
    return () => {
      active = false;
    };
  }, []);

  function handleFileDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const pdfs = Array.from(e.dataTransfer.files).filter(
        (f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")
      );
      if (pdfs.length === 0) {
        setError("Only PDF files are supported.");
        return;
      }
      setSelectedFiles(pdfs);
      setError(null);
    }
  }

  async function upload(assessmentDate: string, filesToUpload: File[], queryText: string) {
    if (!filesToUpload || filesToUpload.length === 0) {
      setError("Please choose or drag-and-drop at least one PDF to assess.");
      return;
    }
    setBusy(true);
    setError(null);
    const formData = new FormData();
    formData.append("assessment_date", assessmentDate);
    formData.append("query", queryText);
    for (const f of filesToUpload) {
      formData.append("files", f);
    }

    try {
      const response = await apiRequest<Job>("/v1/jobs", { method: "POST", body: formData });
      router.push(`/jobs/${encodeURIComponent(response.id)}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Assessment submission failed");
      setBusy(false);
    }
  }

  async function handleSampleClick(sampleName: string) {
    setBusy(true);
    setError(null);
    try {
      // In demo mode or local environment, fetch sample PDF blob
      const res = await fetch(`/api/backend/v1/samples/${sampleName}`).catch(() => null);
      let blob: Blob;
      if (res && res.ok) {
        blob = await res.blob();
      } else {
        // Fallback minimal PDF blob with text
        blob = new Blob(["%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"], {
          type: "application/pdf",
        });
      }
      const file = new File([blob], sampleName, { type: "application/pdf" });
      const today = new Date().toISOString().split("T")[0];
      await upload(today, [file], `Assess ${sampleName}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to load sample document");
      setBusy(false);
    }
  }

  const todayStr = new Date().toISOString().split("T")[0];

  return (
    <>
      <PageTitle
        title="New compliance check"
        description="Upload supplier evidence and verify compliance with rule-based deterministic checks."
      />

      <div className="grid gap-6 md:grid-cols-3">
        <div className="md:col-span-2">
          <Card>
            <h2 className="text-lg font-semibold">Upload document</h2>

            <form
              className="mt-4 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                const formData = new FormData(event.currentTarget);
                const assessmentDate = (formData.get("assessment_date") as string) || todayStr;
                const queryText = (formData.get("query") as string) || "Assess uploaded documents.";
                void upload(assessmentDate, selectedFiles, queryText);
              }}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="assessment_date" className="block text-sm font-medium">
                    Assessment date
                  </label>
                  <input
                    id="assessment_date"
                    name="assessment_date"
                    type="date"
                    defaultValue={todayStr}
                    required
                    className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] px-3 text-sm focus:border-[#176b4a] focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="factory" className="block text-sm font-medium">
                    Factory / Supplier
                  </label>
                  <select
                    id="factory"
                    name="factory"
                    className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] bg-white px-3 text-sm focus:border-[#176b4a] focus:outline-none"
                  >
                    <option value="FAC-001">Sunrise Electronics (Shanghai, CN)</option>
                    <option value="FAC-002">GreenPack Packaging (Berlin, DE)</option>
                    <option value="FAC-003">Apex Textiles (Dhaka, BD)</option>
                    <option value="FAC-004">ClearPath Chemicals (Mumbai, IN)</option>
                  </select>
                </div>
              </div>

              {/* Drag and Drop Zone */}
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleFileDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
                  isDragging
                    ? "border-[#176b4a] bg-[#eaf4ed]"
                    : "border-[#cbd8cf] bg-[#f9faf9] hover:bg-[#f3f6f3]"
                }`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/pdf,.pdf"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files && e.target.files.length > 0) {
                      setSelectedFiles(Array.from(e.target.files));
                      setError(null);
                    }
                  }}
                />
                <p className="text-sm font-semibold text-[#176b4a]">
                  Click to choose or drag and drop PDF files here
                </p>
                <p className="mt-1 text-xs text-[#64736a]">Supports ISO certificates, audit reports, BOMs (max 10MB)</p>
                {selectedFiles.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {selectedFiles.map((file, idx) => (
                      <span
                        key={idx}
                        className="rounded-md bg-[#eaf4ed] px-2.5 py-1 text-xs font-medium text-[#10553a]"
                      >
                        {file.name} ({(file.size / 1024).toFixed(1)} KB)
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label htmlFor="query" className="block text-sm font-medium">
                  Assessment query
                </label>
                <input
                  id="query"
                  name="query"
                  defaultValue="Assess uploaded compliance documents against applicable regulations."
                  maxLength={1000}
                  required
                  className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] px-3 text-sm focus:border-[#176b4a] focus:outline-none"
                />
              </div>

              <Button disabled={busy || selectedFiles.length === 0} className="w-full sm:w-auto">
                {busy ? "Running compliance check…" : "Run compliance check"}
              </Button>
            </form>

            {error && (
              <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}
          </Card>
        </div>

        {/* Try a Sample Document Shortcut Card */}
        <div>
          <Card>
            <h2 className="text-base font-semibold">Try a sample document</h2>
            <p className="mt-1 text-xs text-[#64736a]">
              Instantly run predefined compliance scenarios to observe deterministic verifier decisions.
            </p>
            <div className="mt-4 space-y-2">
              {SAMPLE_FILES.map((sample) => (
                <button
                  type="button"
                  key={sample.name}
                  disabled={busy}
                  onClick={() => void handleSampleClick(sample.name)}
                  className="w-full rounded-lg border border-[#dce5dd] p-3 text-left transition hover:border-[#176b4a] hover:bg-[#f8fbf8] disabled:opacity-50"
                >
                  <p className="text-sm font-medium text-[#176b4a]">{sample.label}</p>
                  <p className="text-xs text-[#64736a]">File: {sample.name}</p>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <Card className="mt-6 overflow-hidden p-0">
        <h2 className="px-5 py-4 font-semibold">Recent assessments</h2>
        {jobs.length === 0 ? (
          <p className="p-5 pt-0 text-sm text-[#64736a]">No recent compliance checks found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-left text-sm">
              <thead className="bg-[#f7f9f7] text-xs uppercase text-[#64736a]">
                <tr>
                  <th className="px-5 py-3">Job ID</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Risk Score</th>
                  <th className="px-5 py-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} className="border-t border-[#edf1ed] hover:bg-[#fafbfa]">
                    <td className="px-5 py-4">
                      <Link
                        className="font-semibold text-[#176b4a] hover:underline"
                        href={`/jobs/${encodeURIComponent(job.id)}`}
                      >
                        {job.id}
                      </Link>
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge>{job.status}</StatusBadge>
                    </td>
                    <td className="px-5 py-4">
                      {job.risk_score !== null ? `${Math.round(job.risk_score * 100)}%` : "—"}
                    </td>
                    <td className="px-5 py-4">{job.assessment_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
