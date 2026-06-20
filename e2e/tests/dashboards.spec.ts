import { test, expect } from '@playwright/test';

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
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
    await page.locator('.nav-tabs .nav-link', { hasText: 'Dashboards' }).click();

    const nowRow = page.locator('.card', { hasText: 'Dashboards' }).locator('tr', { hasText: 'Now' });
    await expect(nowRow.locator('button.btn-outline-danger')).toHaveCount(0);
  });
});
