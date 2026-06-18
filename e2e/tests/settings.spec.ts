import { test, expect } from '@playwright/test';

// Phase 5 read-only settings display end-to-end on the dummy: the backend decodes the
// dummy's settings (work-mode timer + globals + battery) and the Control page renders them.
// Exercises the full stack — register decode → /api/devices/{id}/settings → DOM — which the
// unit/component tests can't span. Deep-linking the SPA route 404s under StaticFiles, so we
// navigate via the sidebar nav (client-side routing).
test.describe('Settings display (read-only, on the dummy)', () => {
  test('Control page renders the decoded work-mode timer + settings', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Control' }).click();

    // Section cards from the dummy's schema.
    await expect(page.getByText('Work-mode timer')).toBeVisible();

    // The 6-slot timer table, with the validated cheap-night-rate plan from the dummy.
    const slotTable = page.locator('table', { has: page.locator('thead') });
    await expect(slotTable.locator('tbody tr')).toHaveCount(6);
    await expect(slotTable).toContainText('00:05'); // slot 1 start time

    // Enum decoded to its label, not the raw machine value.
    await expect(page.getByText('Zero export to CT')).toBeVisible();

    // With control enabled (Phase 6) the page offers editing rather than a read-only notice.
    await expect(page.getByText(/Editing is enabled/)).toBeVisible();
    await expect(page.getByRole('button', { name: /Edit/ }).first()).toBeVisible();
  });
});
