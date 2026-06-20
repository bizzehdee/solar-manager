import { test, expect } from '@playwright/test';

// The live path is the canonical thing unit tests can't span (plan.md §21): a Reading
// produced by the backend poller, pushed over the WebSocket, rendered into the DOM.
test.describe('Now dashboard (live, on the dummy)', () => {
  test('shell renders with brand and sidebar nav', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.navbar-brand')).toContainText('SolarVolt');
    // Dashboards group (Now, History built-ins) + tools group + the "New dashboard" action.
    await expect(page.locator('.app-sidebar .nav-link', { hasText: 'Now' })).toBeVisible();
    await expect(page.locator('.app-sidebar .nav-link', { hasText: 'History' })).toBeVisible();
    await expect(page.locator('.app-sidebar .nav-link', { hasText: 'Settings' })).toBeVisible();
    await expect(page.locator('.app-sidebar .nav-link', { hasText: 'New dashboard' })).toBeVisible();
  });

  test('renders inside the dashboard grid host', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('app-dashboard-host .grid-stack')).toBeVisible();
  });

  test('mobile viewport stacks widgets into a single column', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto('/');
    const items = page.locator('app-dashboard-host .grid-stack-item');
    await expect(items.first()).toBeVisible();
    // In 1-column mode every widget is left-aligned at the same x (stacked vertically).
    const a = await items.nth(0).boundingBox();
    const b = await items.nth(1).boundingBox();
    expect(a && b).toBeTruthy();
    expect(Math.abs((a!.x) - (b!.x))).toBeLessThan(5);
    expect(b!.y).toBeGreaterThan(a!.y); // second widget is below the first, not beside it
  });

  test('battery gauge updates from a live WebSocket reading', async ({ page }) => {
    await page.goto('/');
    // SoC is now a generic metric-gauge (a power-gauge with unit "%"); its value text appears
    // once a snapshot has arrived over the socket.
    await expect(page.locator('app-power-gauge text', { hasText: '%' }).first()).toBeVisible();
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
