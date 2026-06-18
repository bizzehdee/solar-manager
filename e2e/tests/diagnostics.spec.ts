import { test, expect } from '@playwright/test';

// Phase 8 / T092: Diagnostics page on the dummy — build/DB/rollup summary + device table.
test('Diagnostics page shows build info and the device table', async ({ page }) => {
  await page.goto('/');
  await page.locator('.app-sidebar .nav-link', { hasText: 'Diagnostics' }).click();

  await expect(page.getByRole('heading', { name: /Diagnostics/ })).toBeVisible();
  await expect(page.getByText('DB schema')).toBeVisible();
  await expect(page.getByText('Devices', { exact: true })).toBeVisible();
  await expect(page.locator('table tbody tr', { hasText: 'dummy' }).first()).toBeVisible();
});
