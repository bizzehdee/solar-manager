import { test, expect } from '@playwright/test';

// L06 / T_DB5 + L16: the History page is the "history" built-in dashboard — a row of derived-KPI
// metric-cards (self-consumption, savings, …) above a config-driven time-series chart, rendered
// through the dashboard host. The chart has no inline controls; it's configured via the editor.
test.describe('History dashboard (on the dummy)', () => {
  test('renders the KPI cards and the history chart', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'History' }).click();

    await expect(page.locator('app-dashboard-host .grid-stack')).toBeVisible();
    // The KPIs are individual metric-cards now (no single daily-kpis widget).
    await expect(page.locator('app-metric-card').first()).toBeVisible();

    const chart = page.locator('app-history-chart');
    await expect(chart).toBeVisible();
    // Config-driven: no inline selectors; shows a chart canvas or the no-data state on a fresh DB.
    await expect(chart.locator('canvas').or(chart.getByText('No data yet'))).toBeVisible();
    await expect(chart.locator('#hc-metric')).toHaveCount(0);
  });
});
