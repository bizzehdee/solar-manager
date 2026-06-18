import { test, expect } from '@playwright/test';

// Regression guard: on a mobile viewport the sidebar is an off-canvas overlay that must be
// reachable via the hamburger (previously the toggle only drove the desktop `.sidebar-collapsed`
// class, so the menu was permanently off-screen on mobile).
test.use({ viewport: { width: 375, height: 700 } });

test.describe('Mobile sidebar', () => {
  test('hamburger reveals the off-canvas sidebar and a nav tap dismisses it', async ({ page }) => {
    await page.goto('/');
    const backdrop = page.locator('.sidebar-backdrop');

    await expect(backdrop).toBeHidden(); // closed by default on mobile

    await page.getByLabel('Toggle sidebar').click();
    await expect(backdrop).toBeVisible(); // overlay opened

    await page.locator('.app-sidebar .nav-link', { hasText: 'Forecast' }).click();
    await expect(page).toHaveURL(/\/forecast/); // navigated
    await expect(backdrop).toBeHidden(); // and the overlay auto-closed
  });
});
