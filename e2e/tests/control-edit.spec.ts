import { test, expect } from '@playwright/test';

// Phase 6 write-back, end-to-end on the dummy with control enabled (plan.md §12 / T077).
// Drives the full safety loop the unit/component tests can't span as a user:
// edit a work-mode-timer slot → see the current→proposed diff → confirm → the server writes
// in-memory, re-reads and verifies → the read-back-verified value renders and the write is
// logged. The dummy applies writes in-memory, so there's no hardware and no risk.
test.describe('Settings control / write-back (control enabled, on the dummy)', () => {
  test('edit a timer slot → diff → confirm → read-back verified + audited', async ({ page }) => {
    await page.goto('/');
    await page.locator('.app-sidebar .nav-link', { hasText: 'Control' }).click();
    await expect(page.getByText(/Editing is enabled/)).toBeVisible();

    // The timer-slots table; slot 1 starts at Target SoC 65% on the dummy's cheap-night plan.
    const slotTable = page.locator('table', { has: page.locator('thead') });
    const slot1 = slotTable.locator('tbody tr').first();
    await expect(slot1).toContainText('65');

    // Enter edit mode for slot 1 and change Target SoC 65 → 80.
    await slot1.getByRole('button', { name: /Edit/ }).click();
    const socInput = slot1.getByLabel('Target SoC');
    await expect(socInput).toHaveValue('65');
    await socInput.fill('80');

    // Review opens the confirm dialog showing the diff.
    await slot1.getByRole('button', { name: 'Review' }).click();
    const modal = page.locator('.modal');
    await expect(modal).toBeVisible();
    await expect(modal).toContainText('Target SoC');
    await expect(modal).toContainText('65');
    await expect(modal).toContainText('80');

    // Confirm → write → read-back verify.
    await modal.getByRole('button', { name: /Apply/ }).click();
    await expect(page.getByText('Settings written and verified.')).toBeVisible();
    await expect(modal).toBeHidden();

    // The read-back-verified value is now rendered in slot 1, and the write is in the log.
    await expect(slotTable.locator('tbody tr').first()).toContainText('80');
    const recent = page.locator('.card', { hasText: 'Recent changes' });
    await expect(recent).toContainText('timer_slots slot 1');
    await expect(recent.locator('.badge', { hasText: 'ok' }).first()).toBeVisible();
  });
});
