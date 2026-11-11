"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, type DocumentRecord, type Job } from "@/lib/api";
import { Button, Card, PageTitle, StatusBadge } from "@/components/ui";

export function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadJobs() {
    const result = await apiRequest<Job[]>("/v1/jobs");
    setJobs(result);
  }

  useEffect(() => {
    let active = true;
    apiRequest<Job[]>("/v1/jobs").then((result) => {
      if (active) setJobs(result);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load assessments");
    });
    return () => {
      active = false;
    };
  }, []);

  async function upload(formData: FormData) {
    const files = formData.getAll("files");
    if (!files.some((file) => file instanceof File && file.size > 0)) {
      setError("Choose at least one PDF to assess.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await apiRequest<Job>("/v1/jobs", { method: "POST", body: formData });
      setDocuments(await apiRequest<DocumentRecord[]>(`/v1/jobs/${encodeURIComponent(response.id)}/documents`));
      await loadJobs();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Assessment submission failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageTitle title="Documents & jobs" description="Upload supplier evidence and track tenant-scoped assessments." />
      <Card>
        <h2 className="text-lg font-semibold">Start an assessment</h2>
        <form
          className="mt-4 grid gap-4 md:grid-cols-[1fr_1fr_2fr_auto] md:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void upload(new FormData(event.currentTarget));
          }}
        >
          <label className="text-sm font-medium">
            Assessment date
            <input name="assessment_date" type="date" required className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] px-3" />
          </label>
          <label className="text-sm font-medium">
            Supplier documents (PDF)
            <input name="files" type="file" accept="application/pdf,.pdf" multiple required className="mt-1.5 block w-full text-sm file:mr-2 file:rounded-md file:border-0 file:bg-[#eaf4ed] file:px-3 file:py-2" />
          </label>
          <label className="text-sm font-medium">
            Assessment question
            <input name="query" defaultValue="Assess uploaded documents." maxLength={1000} required className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] px-3" />
          </label>
          <Button disabled={busy}>{busy ? "Submitting…" : "Submit"}</Button>
        </form>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {documents.length > 0 && (
          <div className="mt-5 border-t border-[#e7ede8] pt-4">
            <h3 className="font-semibold">Uploaded and linked</h3>
            <ul className="mt-2 list-inside list-disc text-sm text-[#64736a]">
              {documents.map((document) => <li key={document.id}>{document.filename} ({document.page_count} pages)</li>)}
            </ul>
          </div>
        )}
      </Card>
      <Card className="mt-6 overflow-hidden p-0">
        <h2 className="px-5 py-4 font-semibold">Assessments</h2>
        {jobs.length === 0 ? <p className="p-5 pt-0 text-sm text-[#64736a]">No jobs are available for this tenant.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-left text-sm">
              <thead className="bg-[#f7f9f7] text-xs uppercase text-[#64736a]"><tr><th className="px-5 py-3">Job</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Route</th><th className="px-5 py-3">Assessment date</th></tr></thead>
              <tbody>{jobs.map((job) => <tr key={job.id} className="border-t border-[#edf1ed]">
                <td className="px-5 py-4"><Link className="font-semibold text-[#176b4a] hover:underline" href={`/jobs/${encodeURIComponent(job.id)}`}>{job.id}</Link></td>
                <td className="px-5 py-4"><StatusBadge>{job.status}</StatusBadge></td><td className="px-5 py-4">{job.route}</td><td className="px-5 py-4">{job.assessment_date}</td>
              </tr>)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
