import { test, expect } from '@playwright/test';

// L07: the MQTT + Home Assistant card lives on Settings › Notifications. A broker isn't available
// in CI, so we verify the config round-trips (save persists) rather than an actual publish.
test('MQTT settings card saves broker config', async ({ page }) => {
  await page.goto('/');
  await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
  await page.locator('.nav-tabs .nav-link', { hasText: 'Notifications' }).click();

  const card = page.locator('.card', { hasText: 'MQTT + Home Assistant' });
  await expect(card).toBeVisible();

  await card.locator('#mq-host').fill('broker.lan');
  await card.locator('#mq-base').fill('house');
  await card.getByRole('button', { name: /Save/ }).click();
  await expect(card.getByText('Saved.')).toBeVisible();

  // Reload the tab → the saved host is still there (persisted server-side).
  await page.locator('.app-sidebar .nav-link', { hasText: 'Now' }).click();
  await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
  await page.locator('.nav-tabs .nav-link', { hasText: 'Notifications' }).click();
  await expect(card.locator('#mq-host')).toHaveValue('broker.lan');
});
