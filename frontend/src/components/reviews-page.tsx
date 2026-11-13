"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, type Review } from "@/lib/api";
import { Button, Card, PageTitle, StatusBadge } from "@/components/ui";

export function ReviewsPage() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  async function load() {
    setReviews(await apiRequest<Review[]>("/v1/reviews"));
  }

  useEffect(() => {
    let active = true;
    apiRequest<Review[]>("/v1/reviews").then((result) => {
      if (active) setReviews(result);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load reviews");
    });
    return () => { active = false; };
  }, []);

  async function decide(review: Review, decision: "approved" | "rejected" | "more_evidence") {
    setSaving(review.id);
    setError(null);
    try {
      await apiRequest<Review>(`/v1/reviews/${encodeURIComponent(review.id)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, notes: notes[review.id] ?? "" }),
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save review decision");
    } finally {
      setSaving(null);
    }
  }

  const ordered = [...reviews].sort((a, b) => {
    if (a.priority !== b.priority) return a.priority === "critical" ? -1 : 1;
    return a.created_at.localeCompare(b.created_at);
  });

  return (
    <>
      <PageTitle title="Review queue" description="Critical escalations appear first. Decisions are recorded with reviewer notes." />
      {error && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      <div className="space-y-4">
        {ordered.length === 0 && <Card><p className="text-sm text-[#64736a]">No pending reviews.</p></Card>}
        {ordered.map((review) => (
          <Card key={review.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="font-semibold">Review {review.id}</h2><p className="mt-1 text-sm text-[#64736a]">Thread {review.thread_id} · {new Date(review.created_at).toLocaleString()}</p></div>
              <StatusBadge>{review.priority}</StatusBadge>
            </div>
            <p className="mt-3 text-sm">Assessment: <Link className="font-semibold text-[#176b4a] hover:underline" href={`/jobs/${encodeURIComponent(review.job_id)}`}>{review.job_id}</Link></p>
            <label className="mt-4 block text-sm font-medium">
              Reviewer notes
              <textarea value={notes[review.id] ?? ""} onChange={(event) => setNotes((current) => ({ ...current, [review.id]: event.target.value }))} maxLength={4000} rows={3} className="mt-1.5 w-full rounded-lg border border-[#cbd8cf] p-3" />
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button disabled={saving === review.id} onClick={() => void decide(review, "approved")}>Approve</Button>
              <Button variant="danger" disabled={saving === review.id} onClick={() => void decide(review, "rejected")}>Reject</Button>
              <Button variant="secondary" disabled={saving === review.id} onClick={() => void decide(review, "more_evidence")}>Request more evidence</Button>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
