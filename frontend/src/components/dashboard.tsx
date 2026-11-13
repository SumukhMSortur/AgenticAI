"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ClipboardCheck, FileText, ShieldAlert } from "lucide-react";
import { apiRequest, type Job, type Review } from "@/lib/api";
import { Card, PageTitle, StatusBadge } from "@/components/ui";

export function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      apiRequest<Job[]>("/v1/jobs"),
      apiRequest<Review[]>("/v1/reviews"),
    ]).then(([jobRows, reviewRows]) => {
      if (active) {
        setJobs(jobRows);
        setReviews(reviewRows);
      }
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load workspace");
    });
    return () => {
      active = false;
    };
  }, []);

  const critical = reviews.filter((review) => review.priority === "critical").length;
  const completed = jobs.filter((job) => job.status === "completed").length;
  const latest = [...jobs].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5);

  return (
    <>
      <PageTitle
        title="Supply chain overview"
        description="A clear view of current assessments, supplier evidence, and decisions awaiting review."
        action={
          <Link
            href="/jobs"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[#176b4a] px-4 text-sm font-semibold text-white hover:bg-[#10553a]"
          >
            <FileText size={17} aria-hidden="true" />
            New assessment
          </Link>
        }
      />
      {error && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={FileText} label="Total assessments" value={jobs.length} />
        <Metric icon={ClipboardCheck} label="Completed" value={completed} />
        <Metric icon={ShieldAlert} label="Pending reviews" value={reviews.length} />
        <Metric icon={ShieldAlert} label="Critical priority" value={critical} emphasis />
      </div>
      <Card className="mt-6 overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-[#e7ede8] px-5 py-4">
          <div>
            <h2 className="font-semibold">Recent assessments</h2>
            <p className="mt-1 text-sm text-[#64736a]">Latest activity in this tenant</p>
          </div>
          <Link href="/jobs" className="inline-flex items-center gap-1 text-sm font-semibold text-[#176b4a]">
            All jobs <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </div>
        {latest.length === 0 ? (
          <p className="p-6 text-sm text-[#64736a]">No assessments yet. Upload supplier documents to begin.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-left text-sm">
              <thead className="bg-[#f7f9f7] text-xs uppercase text-[#64736a]">
                <tr><th className="px-5 py-3">Assessment</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Risk</th><th className="px-5 py-3">Date</th></tr>
              </thead>
              <tbody>
                {latest.map((job) => (
                  <tr key={job.id} className="border-t border-[#edf1ed]">
                    <td className="px-5 py-4"><Link className="font-semibold text-[#176b4a] hover:underline" href={`/jobs/${encodeURIComponent(job.id)}`}>{job.id}</Link></td>
                    <td className="px-5 py-4"><StatusBadge>{job.status}</StatusBadge></td>
                    <td className="px-5 py-4">{job.risk_score === null ? "—" : `${Math.round(job.risk_score * 100)}%`}</td>
                    <td className="px-5 py-4 text-[#64736a]">{new Date(job.created_at).toLocaleDateString()}</td>
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

function Metric({
  icon: Icon,
  label,
  value,
  emphasis = false,
}: {
  icon: typeof FileText;
  label: string;
  value: number;
  emphasis?: boolean;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between">
        <p className="text-sm text-[#64736a]">{label}</p>
        <Icon size={18} className={emphasis ? "text-amber-700" : "text-[#176b4a]"} aria-hidden="true" />
      </div>
      <p className="mt-4 text-3xl font-semibold">{value}</p>
    </Card>
  );
}
