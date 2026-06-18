import { test, expect } from '@playwright/test';

// Phase 8 / T094: installable PWA — self-hosted manifest, icon and service worker.
test.describe('PWA assets (self-hosted)', () => {
  test('manifest is served, valid, and standalone', async ({ request }) => {
    const res = await request.get('/manifest.webmanifest');
    expect(res.ok()).toBeTruthy();
    const m = await res.json();
    expect(m.name).toBe('SolarVolt');
    expect(m.display).toBe('standalone');
    expect(m.icons.length).toBeGreaterThan(0);
  });

  test('service worker + icon are reachable', async ({ request }) => {
    expect((await request.get('/sw.js')).ok()).toBeTruthy();
    expect((await request.get('/icon.svg')).ok()).toBeTruthy();
  });

  test('index links the manifest', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('link[rel="manifest"]')).toHaveCount(1);
  });
});
