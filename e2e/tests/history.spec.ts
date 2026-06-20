import { test, expect } from '@playwright/test';

// L06 / T_DB5: the History page is the "history" built-in dashboard — a daily-KPI row + an
// interactive metric/resolution/range time-series chart, rendered through the dashboard host.
test.describe('History dashboard (on the dummy)', () => {
  test('renders the dashboard host with the KPI row and chart', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'History' }).click();

    await expect(page.locator('app-dashboard-host .grid-stack')).toBeVisible();
    await expect(page.locator('app-daily-kpis app-stat-card').first()).toBeVisible();
    await expect(page.locator('app-history-chart')).toBeVisible();
  });

  test('exposes the metric/resolution/range selectors in the chart widget', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'History' }).click();

    const widget = page.locator('app-history-chart');
    await expect(widget.locator('#hc-metric')).toBeVisible();
    await expect(widget.locator('#hc-res')).toBeVisible();
    await expect(widget.locator('#hc-range')).toBeVisible();
    // The widget shows its data once loaded: a chart canvas, or the no-data state on a fresh DB.
    await expect(widget.locator('canvas, .alert')).toHaveCount(1);
  });
});
