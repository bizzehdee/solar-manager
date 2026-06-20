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

  test('built-in dashboards cannot be deleted', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
    await page.locator('.nav-tabs .nav-link', { hasText: 'Dashboards' }).click();

    const nowRow = page.locator('.card', { hasText: 'Dashboards' }).locator('tr', { hasText: 'Now' });
    await expect(nowRow.locator('button.btn-outline-danger')).toHaveCount(0);
  });
});
