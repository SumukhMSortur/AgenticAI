import { expect, test } from "@playwright/test";

test("supplier assessment, evidence review, and workspace pages", async ({ page }) => {
  const job = {
    id: "job-e2e",
    status: "completed",
    route: "full_analysis",
    assessment_date: "2026-01-01",
    risk_score: 0.32,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:01:00Z",
  };
  const document = {
    id: "doc-e2e",
    filename: "supplier-evidence.pdf",
    mime_type: "application/pdf",
    page_count: 2,
    doc_hash: "sha256-e2e",
    created_at: "2026-01-01T10:00:00Z",
  };
  const review = {
    id: "review-e2e",
    job_id: job.id,
    thread_id: "thread-e2e",
    status: "pending",
    decision: null,
    decision_notes: null,
    created_at: "2026-01-01T10:02:00Z",
    priority: "critical",
  };
  const scorecard = {
    job_id: job.id,
    tenant_id: "tenant-e2e",
    assessment_date: job.assessment_date,
    overall_status: "review_required",
    risk_score: job.risk_score,
    re_audit_recommended: false,
    summary: "Supplier certificate evidence requires human review.",
    lines: [
      {
        claim: {
          claim_id: "claim-e2e",
          claim_text: "Valid supplier certificate",
          doc_id: document.id,
          doc_hash: document.doc_hash,
          page: 1,
          bbox: { x0: 100, y0: 200, x1: 600, y1: 700 },
          evidence_ids: ["evidence-e2e"],
          regulation_version: "2026",
        },
        verdict: {
          outcome: "escalate",
          reason_code: "human_review",
          rule_id: "CERT-001",
          details: {},
        },
        evidence: [
          { evidence_id: "evidence-e2e", kind: "document_text", ref: { page: 1 } },
        ],
      },
    ],
  };
  let decidedReview = { ...review };
  let submittedDecision: { decision: string; notes: string } | null = null;
  let reviewReads = 0;
  let uploadedEvidence = false;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();

    if (pathname === "/api/auth/login" && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: {
          "Set-Cookie": "ecochain_session=e2e-session-token; Path=/; HttpOnly; SameSite=Strict",
        },
        body: JSON.stringify({ authenticated: true }),
      });
      return;
    }

    if (pathname === "/api/backend/v1/jobs" && method === "POST") {
      const body = request.postDataBuffer()?.toString("utf8") ?? "";
      uploadedEvidence = body.includes(document.filename) && body.includes("%PDF-1.4");
      await route.fulfill({ json: job });
      return;
    }
    if (pathname === "/api/backend/v1/jobs") {
      await route.fulfill({ json: [job] });
      return;
    }
    if (pathname === `/api/backend/v1/jobs/${job.id}`) {
      await route.fulfill({ json: job });
      return;
    }
    if (pathname === `/api/backend/v1/jobs/${job.id}/documents`) {
      await route.fulfill({ json: [document] });
      return;
    }
    if (pathname === `/api/backend/v1/jobs/${job.id}/scorecard`) {
      await route.fulfill({ json: scorecard });
      return;
    }
    if (pathname === `/api/backend/v1/jobs/${job.id}/events`) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "event: step\ndata: Supplier evidence extracted\n\n",
      });
      return;
    }
    if (pathname === `/api/backend/v1/documents/${document.id}/pages/1.png`) {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=",
          "base64",
        ),
      });
      return;
    }
    if (pathname === "/api/backend/v1/reviews" && method === "GET") {
      reviewReads += 1;
      await route.fulfill({ json: [decidedReview] });
      return;
    }
    if (pathname === `/api/backend/v1/reviews/${review.id}/decision` && method === "POST") {
      const body = request.postDataJSON() as { decision: string; notes: string };
      submittedDecision = body;
      decidedReview = {
        ...review,
        status: "approved",
        decision: body.decision,
        decision_notes: body.notes,
      };
      await route.fulfill({ json: decidedReview });
      return;
    }
    if (pathname === "/api/backend/v1/factories") {
      await route.fulfill({
        json: [{ id: "factory-e2e", name: "Example Factory", country: "Portugal", external_id: null }],
      });
      return;
    }
    if (pathname === "/api/backend/v1/factories/factory-e2e/risk") {
      await route.fulfill({
        json: {
          factory_id: "factory-e2e",
          job_id: job.id,
          risk_score: 0.32,
          model_tag: "xgboost",
          created_at: "2026-01-01T10:01:00Z",
          baseline_comparison: { cohort: "textiles" },
        },
      });
      return;
    }
    if (pathname === "/api/backend/v1/audit-events") {
      await route.fulfill({
        json: [{
          id: 1,
          sequence: 1,
          event_type: "review_decision",
          timestamp: "2026-01-01T10:02:00Z",
          prev_hash: "0".repeat(64),
          event_hash: "1".repeat(64),
          prompt_version: null,
          reviewer_decision: { decision: "approved" },
          verdicts: null,
          payload: null,
        }],
      });
      return;
    }
    if (pathname === "/api/backend/v1/integrations/status") {
      await route.fulfill({
        json: [{
          source: "Issuer registry",
          status: "snapshot_only",
          health: "healthy",
          live_enabled: false,
          record_count: 12,
          age_days: 1,
          as_of: "2026-01-01T10:00:00Z",
        }],
      });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: `Unhandled E2E request: ${method} ${pathname}` } });
  });

  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill("reviewer@example.test");
  await page.getByLabel("Password").fill("development-only-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Supply chain overview" })).toBeVisible();

  await page.getByRole("link", { name: "Documents & jobs" }).click();
  await page.getByLabel("Assessment date").fill("2026-01-01");
  await page.getByLabel("Supplier documents (PDF)").setInputFiles({
    name: document.filename,
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n% E2E fixture\n"),
  });
  await page.getByRole("button", { name: "Submit" }).click();
  await expect.poll(() => uploadedEvidence).toBe(true);
  await expect(page.getByRole("heading", { name: "Uploaded and linked" })).toBeVisible();
  await page.getByRole("link", { name: job.id }).click();

  await expect(page.getByRole("heading", { name: `Assessment ${job.id}` })).toBeVisible();
  await expect(page.getByText("Supplier evidence extracted")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence scorecard" })).toBeVisible();
  await page.getByRole("button", { name: /Valid supplier certificate/ }).click();
  await expect(page.getByRole("img", { name: `${document.filename}, page 1` })).toBeVisible();
  await expect(page.locator('[aria-label="Evidence location"]')).toBeVisible();

  await page.getByRole("link", { name: "Review queue" }).click();
  await page.getByLabel("Reviewer notes").fill("Evidence reviewed in the E2E workflow.");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect.poll(() => submittedDecision).toEqual({
    decision: "approved",
    notes: "Evidence reviewed in the E2E workflow.",
  });
  await expect.poll(() => reviewReads).toBeGreaterThan(1);

  await page.getByRole("link", { name: "Factory risk" }).click();
  await expect(page.getByRole("heading", { name: "Factory risk" })).toBeVisible();
  await expect(page.getByLabel("Factory")).toHaveValue("factory-e2e");
  await expect(page.getByRole("meter", { name: "Six-month audit failure risk" })).toHaveAttribute("aria-valuenow", "32");

  await page.getByRole("link", { name: "Audit trail" }).click();
  await expect(page.getByRole("heading", { name: "Audit trail" })).toBeVisible();
  await expect(page.getByText("review_decision")).toBeVisible();

  await page.getByRole("link", { name: "Integrations" }).click();
  await expect(page.getByRole("heading", { name: "Integration status" })).toBeVisible();
  await expect(page.getByText("Issuer registry")).toBeVisible();
});
