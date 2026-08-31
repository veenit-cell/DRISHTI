import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { installSyntheticApi } from "../e2e/fixtures";

test.describe("operator accessibility states", () => {
  test("loading state has no axe violations", async ({ page }) => {
    await installSyntheticApi(page, false, 1_500);
    await page.goto("/?mode=synthetic");
    await expect(page.getByRole("status")).toContainText("Connecting");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test("interactive synthetic state has no axe violations", async ({ page }) => {
    await installSyntheticApi(page);
    await page.goto("/?mode=synthetic");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test("degraded state has no axe violations", async ({ page }) => {
    await installSyntheticApi(page, true);
    await page.goto("/?mode=live");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test("offline state has no axe violations", async ({ page }) => {
    await installSyntheticApi(page, false, 0, true);
    await page.goto("/?mode=live");
    await page.getByRole("button", { name: "Work Offline" }).click();
    await expect(page.getByText(/Working offline/)).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});
