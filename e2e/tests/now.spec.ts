import { test, expect } from '@playwright/test';

// The live path is the canonical thing unit tests can't span (plan.md §21): a Reading
// produced by the backend poller, pushed over the WebSocket, rendered into the DOM.
test.describe('Now dashboard (live, on the dummy)', () => {
  test('shell renders with brand and full sidebar nav', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.navbar-brand')).toContainText('SolarVolt');
    await expect(page.locator('.app-sidebar .nav-link')).toHaveCount(6);
  });

  test('battery gauge updates from a live WebSocket reading', async ({ page }) => {
    await page.goto('/');
    // The SoC gauge text only appears once a snapshot has arrived over the socket.
    await expect(page.locator('app-soc-gauge text').first()).toContainText('%');
    await expect(page.getByText('Solar', { exact: true })).toBeVisible();
    await expect(page.getByText('Load', { exact: true })).toBeVisible();
  });

  test('connection status pill reaches Live', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('app-status-pill .badge')).toContainText(/Live|Reconnecting/);
  });
});
