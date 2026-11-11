import { expect, test } from "@playwright/test";

test("authenticated dashboard and critical-first review queue render", async ({ context, page }) => {
  await context.addCookies([
    {
      name: "ecochain_session",
      value: "e2e-session-token",
      url: "http://127.0.0.1:3000",
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
  await page.route("**/api/backend/v1/jobs**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "job-e2e",
          status: "completed",
          route: "full_analysis",
          assessment_date: "2026-01-01",
          risk_score: 0.18,
          created_at: "2026-01-01T10:00:00Z",
          updated_at: "2026-01-01T10:01:00Z",
        },
      ]),
    }),
  );
  await page.route("**/api/backend/v1/reviews**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "normal-review",
          job_id: "job-e2e",
          thread_id: "thread-normal",
          status: "pending",
          decision: null,
          decision_notes: null,
          created_at: "2026-01-02T10:00:00Z",
          priority: "normal",
        },
        {
          id: "critical-review",
          job_id: "job-e2e",
          thread_id: "thread-critical",
          status: "pending",
          decision: null,
          decision_notes: null,
          created_at: "2026-01-03T10:00:00Z",
          priority: "critical",
        },
      ]),
    }),
  );

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Supply chain overview" })).toBeVisible();
  await expect(page.getByRole("link", { name: "job-e2e" })).toBeVisible();
  await page.goto("/reviews");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  const cards = page.locator("section").filter({ hasText: "Review " });
  await expect(cards.first()).toContainText("critical-review");
  await expect(cards.last()).toContainText("normal-review");
});
