import { test, expect } from '@playwright/test';
import { login } from './helpers.js';

test('lien d’évitement, focus et clavier des drawers', async ({ page }) => {
  await login(page);
  await page.goto('/');
  await page.keyboard.press('Tab');
  const skip = page.locator('.skip-link');
  await expect(skip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();

  await page.goto('/offers');
  const row = page.locator('.offer-row').first();
  await expect(row).toHaveAttribute('role', 'button');
  await row.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#offer_drawer')).toHaveClass(/open/);
  await expect(page.locator('#drawer_close')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(row).toBeFocused();
  await page.keyboard.press(' ');
  await expect(page.locator('#offer_drawer')).toHaveClass(/open/);
  await page.keyboard.press('Escape');
});

test('dialogue destructif accessible et restauration du focus', async ({ page }) => {
  await login(page);
  await page.evaluate(async () => {
    const response = await fetch('/api/backups', { method: 'POST' });
    if (!response.ok) throw new Error(await response.text());
  });
  await page.goto('/profile');
  const trigger = page.locator('[data-delete]').first();
  await trigger.click();
  const dialog = page.locator('#action_dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute('role', 'alertdialog');
  await expect(dialog.locator('#action_dialog_cancel')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test('aucun débordement horizontal aux largeurs cibles', async ({ page }) => {
  await login(page);
  for (const width of [1280, 900, 768, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const path of ['/admin', '/admin/audit', '/admin/diagnostics', '/offers']) {
      await page.goto(path);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${path} déborde à ${width}px`).toBeLessThanOrEqual(1);
    }
  }
});
