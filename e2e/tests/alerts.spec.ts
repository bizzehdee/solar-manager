import { test, expect } from '@playwright/test';

// Phase 7 alerts + Prometheus, end-to-end on the dummy. The rule engine runs server-side;
// here we just verify the inbox renders and the Prometheus endpoint serves live metrics.
test.describe('Alerts inbox + Prometheus (on the dummy)', () => {
  test('Alerts page loads with the active/history toggle', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Alerts' }).click();

    await expect(page.getByRole('heading', { name: /Alerts/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Active/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /History/ })).toBeVisible();
  });

  test('Prometheus /metrics exposes live numeric gauges', async ({ request }) => {
    const res = await request.get('/metrics');
    expect(res.ok()).toBeTruthy();
    const body = await res.text();
    expect(body).toContain('solarvolt_battery_soc_pct{device="dummy"}');
  });

  // L11: create → list → delete an automation rule from the Automation page (round-trip via
  // the API, which the engine reloads). Rule editing is ungated (not behind the control flag).
  // Rule authoring moved from the Alerts inbox to the Automation page in L03e-5c.
  test('create and delete an automation rule', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Automation' }).click();

    // Default state: no rules on a fresh dummy.
    await expect(page.getByText('No rules yet')).toBeVisible();

    // New rule → fill the form → save.
    await page.getByRole('button', { name: /New rule/ }).click();
    await page.locator('#a-name').fill('E2E test rule');
    await page.locator('#at0').selectOption('timer_slots|target_soc_pct');
    await page.locator('#ai0').fill('0');
    await page.locator('#av0').fill('80');
    await page.locator('#ae0').check();
    await page.getByRole('button', { name: /Save rule/ }).click();

    // It appears in the list.
    const ruleItem = page.locator('.list-group-item', { hasText: 'E2E test rule' });
    await expect(ruleItem).toBeVisible();

    // Delete it; it disappears.
    await ruleItem.getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByText('E2E test rule')).toHaveCount(0);
  });
});
