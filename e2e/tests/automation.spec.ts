import { test, expect } from '@playwright/test';

// Rule-based automation, end-to-end on the dummy. Automation needs no flag; the e2e backend runs
// with SOLARVOLT_ENABLE_CONTROL on, so "Apply now" is available and actually writes to the dummy
// (in-memory). Builds an armed rule through the editor, sees it in the live "what it would do now"
// preview, then applies it and confirms the write landed.
test.describe('Automation rule editor + live preview + apply (on the dummy)', () => {
  test('create a rule → it lists → live preview reflects it → apply writes it', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Automation' }).click();
    await expect(page.getByRole('heading', { name: /Automation/ })).toBeVisible();

    // New rule: name it, add a day-of-week condition and tick every day so it matches whenever
    // CI runs (the backend uses the real clock), then add an action and arm it.
    await page.getByRole('button', { name: /New rule/ }).click();
    await page.locator('#a-name').fill('E2E weekend top-up');
    await page.getByRole('button', { name: /Add condition/ }).click();
    for (let d = 0; d < 7; d++) await page.locator(`#d0-${d}`).check();
    // Action: set work-mode timer slot 1 target SoC to 80% (an automation-safe target), and arm it.
    await page.getByRole('button', { name: /Add action/ }).click();
    await page.locator('#at0').selectOption('timer_slots|target_soc_pct');
    await page.locator('#ai0').fill('1');
    await page.locator('#av0').fill('80');
    await page.locator('#ae0').check();
    await page.getByRole('button', { name: /Save rule/ }).click();

    // It appears in the rules list; arm the rule itself via its row switch.
    const row = page.locator('.list-group-item', { hasText: 'E2E weekend top-up' });
    await expect(row).toBeVisible();
    await row.getByRole('switch', { name: /Arm E2E weekend top-up/ }).check();

    // The live preview reflects it (every day is ticked, so it always matches) and says it would apply.
    const preview = page.locator('.card', { hasText: 'What it would do now' });
    await expect(preview).toContainText('E2E weekend top-up');
    await expect(preview).toContainText('would apply');

    // Apply now (control is on) writes the armed winner to the dummy and reports success.
    await page.getByRole('button', { name: /Apply now/ }).click();
    await expect(page.locator('.alert-success', { hasText: /Applied 1 change/ })).toBeVisible();
  });
});
