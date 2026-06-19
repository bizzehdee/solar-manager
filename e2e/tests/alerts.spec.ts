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

  // L11: create → list → delete an alert rule from the Rules tab (round-trip via the API,
  // which the engine reloads). Rule editing is ungated (not behind the control flag).
  test('create and delete an alert rule from the Rules tab', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Alerts' }).click();
    await page.getByRole('button', { name: 'Rules', exact: true }).click();

    // Default rules are seeded and listed.
    await expect(page.getByText('Low battery SoC')).toBeVisible();

    // New rule → fill the form → save.
    await page.getByRole('button', { name: /New rule/ }).click();
    await page.locator('#r-name').fill('E2E hot inverter');
    await page.locator('#r-metric').selectOption('inverter_temp_c');
    await page.locator('#r-op').selectOption('gt');
    await page.locator('#r-thr').fill('65');
    await page.getByRole('button', { name: /Save rule/ }).click();

    // It appears in the list with its summary.
    const row = page.locator('.list-group-item', { hasText: 'E2E hot inverter' });
    await expect(row).toBeVisible();
    await expect(row).toContainText('inverter_temp_c > 65');

    // Delete it; it disappears.
    await row.getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByText('E2E hot inverter')).toHaveCount(0);
  });
});
