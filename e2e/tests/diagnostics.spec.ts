import { test, expect } from '@playwright/test';

// Phase 8 / T092: Diagnostics — build/DB/rollup summary + device table. It now lives as a tab
// inside Settings (no longer a top-level sidebar item), so navigate there and open the tab.
test('Diagnostics tab in Settings shows build info and the device table', async ({ page }) => {
  await page.goto('/');
  await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
  await page.locator('.nav-tabs .nav-link', { hasText: 'Diagnostics' }).click();

  const diag = page.locator('app-diagnostics');
  await expect(diag.getByRole('heading', { name: /Diagnostics/ })).toBeVisible();
  await expect(diag.getByText('DB schema')).toBeVisible();
  await expect(diag.getByText('Devices', { exact: true })).toBeVisible();
  await expect(diag.locator('table tbody tr', { hasText: 'dummy' }).first()).toBeVisible();
});
