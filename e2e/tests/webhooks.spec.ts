import { test, expect } from '@playwright/test';

// L15: custom webhooks are dynamic add/edit/remove lists on Settings › Notifications (alert
// webhooks + outbound readings webhooks). A real external endpoint isn't reachable in CI, so we
// verify the user-facing round-trip — add an endpoint, save, and confirm it persists — rather than
// an actual delivery (the POST path is covered by unit/integration tests with an injected client).
// Wait for the readings-webhooks GET before interacting so a slow response can't clobber the form.
const readingsLoaded = (page: import('@playwright/test').Page) =>
  page.waitForResponse(
    (r) => r.url().includes('/api/integrations/readings-webhooks') && r.request().method() === 'GET',
  );

test('add and persist an outbound readings webhook', async ({ page }) => {
  await page.goto('/');
  const loaded = readingsLoaded(page);
  await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
  await loaded;
  await page.locator('.nav-tabs .nav-link', { hasText: 'Notifications' }).click();

  const card = page.locator('.card', { hasText: 'Outbound readings webhooks' });
  await expect(card).toBeVisible();

  await card.getByRole('button', { name: /Add webhook/ }).click();
  await card.getByLabel('Webhook label').fill('Node-RED');
  await card.getByLabel('Webhook URL').fill('http://127.0.0.1:9/sink');
  await card.getByRole('button', { name: 'Save' }).click();
  await expect(card.getByText('Saved.')).toBeVisible();

  // Reload the tab → the saved endpoint is still there (persisted server-side, id assigned).
  await page.locator('.app-sidebar .nav-link', { hasText: 'Now' }).click();
  await page.locator('.app-sidebar .nav-link', { hasText: 'Settings' }).click();
  await page.locator('.nav-tabs .nav-link', { hasText: 'Notifications' }).click();
  await expect(card.getByLabel('Webhook label')).toHaveValue('Node-RED');
});
