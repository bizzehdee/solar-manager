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
});
