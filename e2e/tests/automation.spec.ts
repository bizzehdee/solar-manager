import { test, expect } from '@playwright/test';

// L03e-4 rule-based automation, end-to-end on the dummy with automation enabled. Builds a rule
// through the editor, then sees it listed and reflected in the live "what it would do now"
// preview. Suggest-only — the preview never writes to the device.
test.describe('Automation rule editor + live preview (on the dummy)', () => {
  test('create a rule → it lists → live preview reflects it', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Automation' }).click();
    await expect(page.getByRole('heading', { name: /Automation/ })).toBeVisible();

    // New rule: name it, add a day-of-week condition and tick every day so it matches whenever
    // CI runs (the backend uses the real clock), then add an action.
    await page.getByRole('button', { name: /New rule/ }).click();
    await page.locator('#a-name').fill('E2E weekend top-up');
    await page.getByRole('button', { name: /Add condition/ }).click();
    for (let d = 0; d < 7; d++) await page.locator(`#d0-${d}`).check();
    await page.getByRole('button', { name: /Add action/ }).click();
    await page.getByRole('button', { name: /Save rule/ }).click();

    // It appears in the rules list…
    const row = page.locator('.list-group-item', { hasText: 'E2E weekend top-up' });
    await expect(row).toBeVisible();

    // …and the live preview reflects it (every day is ticked, so it always matches).
    const preview = page.locator('.card', { hasText: 'What it would do now' });
    await expect(preview).toContainText('E2E weekend top-up');
  });
});
