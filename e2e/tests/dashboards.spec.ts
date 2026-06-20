import { test, expect } from '@playwright/test';
import { readFileSync } from 'fs';

async function openDashboardsTab(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
  await page.locator('.nav-tabs .nav-link', { hasText: 'Dashboards' }).click();
  return page.locator('.card', { hasText: 'Dashboards' });
}

// L06 / T_DB6: dashboard switcher + management. Create a user dashboard, see it in the sidebar +
// Settings list, then delete it. Built-ins (Now, History) have no delete control.
test.describe('Dashboard management', () => {
  test('create then delete a user dashboard via Settings', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
    await page.locator('.nav-tabs .nav-link', { hasText: 'Dashboards' }).click();

    const card = page.locator('.card', { hasText: 'Dashboards' });
    await expect(card.getByText('Now')).toBeVisible();
    await expect(card.getByText('History')).toBeVisible();

    // "New" opens a Bootstrap modal asking for the name.
    await card.getByRole('button', { name: /New/ }).click();
    const modal = page.locator('.modal');
    await expect(modal).toBeVisible();
    await modal.locator('#dlg-input').fill('E2E Test Dash');
    await modal.getByRole('button', { name: 'Create' }).click();

    await expect(card.getByRole('cell', { name: 'E2E Test Dash' })).toBeVisible();
    // It also shows up in the sidebar switcher.
    await expect(page.locator('.app-sidebar .nav-link', { hasText: 'E2E Test Dash' })).toBeVisible();

    // Delete it via the confirm modal. The delete control is the red icon button in the row.
    const row = card.locator('tr', { hasText: 'E2E Test Dash' });
    await row.locator('button.btn-outline-danger').click();
    await page.locator('.modal').getByRole('button', { name: 'Delete' }).click();
    await expect(card.getByRole('cell', { name: 'E2E Test Dash' })).toHaveCount(0);
  });

  test('edit a user dashboard: add a widget, save, persists on reload', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
    await page.locator('.nav-tabs .nav-link', { hasText: 'Dashboards' }).click();
    const card = page.locator('.card', { hasText: 'Dashboards' });

    // Create a fresh user dashboard and open it from the sidebar.
    await card.getByRole('button', { name: /New/ }).click();
    await page.locator('.modal #dlg-input').fill('Edit Round Trip');
    await page.locator('.modal').getByRole('button', { name: 'Create' }).click();
    await page.locator('.app-sidebar .nav-link', { hasText: 'Edit Round Trip' }).click();

    // The user dashboard page renders its host.
    const host = page.locator('app-dashboard-host');
    await expect(page.getByRole('heading', { name: 'Edit Round Trip' })).toBeVisible();

    // Enter edit mode, add a widget, and save.
    await host.getByRole('button', { name: 'Edit' }).click();
    await host.locator('select').selectOption('metric-gauge');
    await expect(page.locator('.grid-stack-item')).toHaveCount(1);
    const saveResp = page.waitForResponse((r) => r.url().includes('/api/dashboards/edit-round-trip') && r.request().method() === 'PUT');
    await host.getByRole('button', { name: 'Save' }).click();
    await saveResp;
    await expect(page.locator('.grid-stack-item')).toHaveCount(1); // still there after save

    // Reload the page — the saved widget is still there.
    await page.reload();
    await expect(page.locator('.grid-stack-item')).toHaveCount(1);

    // Cleanup so the dashboard doesn't leak into other tests in the run.
    await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
    await page.locator('.nav-tabs .nav-link', { hasText: 'Dashboards' }).click();
    const row = card.locator('tr', { hasText: 'Edit Round Trip' });
    await row.locator('button.btn-outline-danger').click();
    await page.locator('.modal').getByRole('button', { name: 'Delete' }).click();
  });

  test('built-in dashboards cannot be deleted', async ({ page }) => {
    const nowRow = (await openDashboardsTab(page)).locator('tr', { hasText: 'Now' });
    await expect(nowRow.locator('button.btn-outline-danger')).toHaveCount(0);
  });

  test('export then re-import reproduces the layout (T_DB8)', async ({ page }) => {
    const card = await openDashboardsTab(page);

    // Export the Now built-in (download → read its JSON).
    const nowRow = card.locator('tr', { hasText: 'Now' });
    const download = await Promise.all([
      page.waitForEvent('download'),
      nowRow.locator('button.btn-outline-secondary').first().click(),
    ]).then(([d]) => d);
    const exported = JSON.parse(readFileSync(await download.path(), 'utf8'));
    expect(exported.widgets.length).toBeGreaterThan(0);

    // Re-import the same JSON → a clean import (all known types) navigates to the new copy.
    await card.locator('input[type=file]').setInputFiles({
      name: 'now.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(exported)),
    });
    await expect(page.getByRole('heading', { name: 'Now (2)' })).toBeVisible();
    await expect(page.locator('app-dashboard-host .grid-stack-item')).toHaveCount(exported.widgets.length);

    // Cleanup.
    const card2 = await openDashboardsTab(page);
    const row = card2.locator('tr', { hasText: 'Now (2)' });
    await row.locator('button.btn-outline-danger').click();
    await page.locator('.modal').getByRole('button', { name: 'Delete' }).click();
  });

  test('import: invalid JSON shows an error, unknown widget type warns but succeeds (T_DB8)', async ({ page }) => {
    const card = await openDashboardsTab(page);

    // Invalid JSON → error, stays on the page.
    await card.locator('input[type=file]').setInputFiles({
      name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('not json at all'),
    });
    await expect(card.getByText(/isn't a valid dashboard/i)).toBeVisible();

    // Unknown widget type → warning, but the dashboard is still created (renders a placeholder).
    const doc = { name: 'Mystery Dash', widgets: [{ type: 'mystery', x: 0, y: 0, w: 2, h: 2, config: {} }] };
    await card.locator('input[type=file]').setInputFiles({
      name: 'mystery.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(doc)),
    });
    await expect(card.getByText(/unknown widget type/i)).toBeVisible();
    await expect(card.getByRole('cell', { name: 'Mystery Dash' })).toBeVisible();

    // Cleanup.
    const row = card.locator('tr', { hasText: 'Mystery Dash' });
    await row.locator('button.btn-outline-danger').click();
    await page.locator('.modal').getByRole('button', { name: 'Delete' }).click();
  });
});
