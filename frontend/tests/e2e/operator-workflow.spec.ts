import { expect, test } from "@playwright/test";
import { installSyntheticApi } from "./fixtures";

test.describe("synthetic operator workflow", () => {
  test("renders the decision workflow with explicit synthetic provenance", async ({ page }) => {
    await installSyntheticApi(page);
    await page.goto("/?mode=synthetic");
    await expect(page.getByText("Decision Pulse")).toBeVisible();
    await expect(page.getByText("What needs attention now?")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Decision Queue" })).toBeVisible();
    await expect(page.getByText(/Synthetic/).first()).toBeVisible();
    await expect(page.getByText("No telemetry does not mean safe conditions.")).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: /updated|connected|synthetic/i }).first()).toBeVisible();
  });

  test("keeps a degraded read visibly degraded", async ({ page }) => {
    await installSyntheticApi(page, true);
    await page.goto("/?mode=live");
    await expect(page.getByRole("alert").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /retry/i }).first()).toBeVisible();
  });
});
