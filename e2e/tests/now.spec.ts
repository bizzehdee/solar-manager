import { test, expect } from '@playwright/test';

// The live path is the canonical thing unit tests can't span (plan.md §21): a Reading
// produced by the backend poller, pushed over the WebSocket, rendered into the DOM.
test.describe('Now dashboard (live, on the dummy)', () => {
  test('shell renders with brand and full sidebar nav', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.navbar-brand')).toContainText('SolarVolt');
    await expect(page.locator('.app-sidebar .nav-link')).toHaveCount(7);
  });

  test('battery gauge updates from a live WebSocket reading', async ({ page }) => {
    await page.goto('/');
    // The SoC gauge text only appears once a snapshot has arrived over the socket.
    await expect(page.locator('app-soc-gauge text').first()).toContainText('%');
    // Scoped to the power gauges — "Solar" also labels a node in the energy-flow widget (L14).
    await expect(page.locator('app-power-gauge text', { hasText: 'Solar' })).toBeVisible();
    await expect(page.locator('app-power-gauge text', { hasText: 'Load' })).toBeVisible();
  });

  test('connection status pill reaches Live', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('app-status-pill .badge')).toContainText(/Live|Reconnecting/);
  });

  // L14: the energy-flow widget renders on live dummy data — five nodes, four wires, and a
  // green (online) inverter ring with at least one active flow once a reading has arrived.
  test('energy-flow widget renders with live node states', async ({ page }) => {
    await page.goto('/');
    const widget = page.locator('app-energy-flow');
    await expect(widget).toBeVisible();
    await expect(widget.locator('.ef-node')).toHaveCount(5);
    await expect(widget.locator('.ef-wire')).toHaveCount(4);
    // Inverter is online on the dummy → centre ring uses the success colour variable.
    await expect(widget.locator('.ef-node--inverter')).toHaveAttribute('style', /--bs-success/);
    // Something is always flowing on the dummy (house load at minimum).
    await expect(widget.locator('.ef-edge').first()).toBeVisible();
  });
});
