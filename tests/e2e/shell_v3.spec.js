import { test, expect } from '@playwright/test';
import { login } from './helpers.js';

test('thème persistant et navigation v3 sur les pages réelles', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'Activer le thème sombre' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('link', { name: 'Vue d’ensemble', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: 'Activer le thème clair' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  for (const theme of ['light', 'dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('[data-theme-toggle]').click();
    for (const route of ['/admin', '/admin/diagnostics']) {
      await page.goto(route);
      const selector = route === '/admin' ? '.admin-state, .admin-pill[class*="invite-"]' : '.diagnostic-check > span';
      await expect(page.locator(selector).first()).toBeVisible();
      const samples = await page.locator(selector).evaluateAll((elements) => {
        const rgb = (value) => value.match(/[\d.]+/g).map(Number);
        const luminance = (color) => color.slice(0, 3).map((channel) => {
          const value = channel / 255;
          return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
        return elements.map((element) => {
          let parent = element;
          let background;
          while (parent) {
            const color = rgb(getComputedStyle(parent).backgroundColor);
            if (color.length === 3 || color[3] === 1) { background = color; break; }
            parent = parent.parentElement;
          }
          const foreground = luminance(rgb(getComputedStyle(element).color));
          const back = luminance(background);
          return { label: element.textContent.trim(), ratio: (Math.max(foreground, back) + 0.05) / (Math.min(foreground, back) + 0.05) };
        });
      });
      expect(samples.length).toBeGreaterThan(0);
      for (const sample of samples) expect(sample.ratio, `${theme}, ${route}, ${sample.label}`).toBeGreaterThanOrEqual(4.5);
    }
  }
});

test('dashboard : compteurs issus des API et isolation entre comptes', async ({ browser }) => {
  const admin = await browser.newPage();
  await login(admin);
  const expected = await Promise.all([
    admin.request.get('/api/offers?view=latest'),
    admin.request.get('/api/offers?view=latest&status=qualified'),
    admin.request.get('/api/offers?view=latest&status=review_required'),
  ]);
  const totals = await Promise.all(expected.map(async (response) => (await response.json()).total));
  await admin.goto('/dashboard');
  for (const [index, selector] of ['#dashboard_total', '#dashboard_qualified', '#dashboard_review'].entries()) {
    await expect(admin.locator(selector)).toHaveText(String(totals[index]));
  }
  await expect(admin.locator('#dashboard_selection')).not.toContainText('Camille Exemple');
  await admin.close();
  const member = await browser.newPage();
  await login(member, 'member', 'member-correct-password');
  await member.goto('/dashboard');
  await expect(member.locator('#dashboard_total')).toHaveText('0');
  await expect(member.locator('#dashboard_selection')).toContainText('Pas encore d’offre qualifiée');
  await expect(member.getByRole('link', { name: 'Administration', exact: true })).toHaveCount(0);
  await member.close();
});

test('lien direct vers une analyse et conservation après actualisation', async ({ page }) => {
  await login(page);
  const url = 'https://jobs.example.test/review-required';
  await page.goto('/offers?open=' + encodeURIComponent(url));
  await expect(page.locator('#offer_drawer')).toHaveClass(/open/);
  await expect(page.locator('#offer_detail')).toContainText('première mission non confirmée');
  await expect(page.locator('#offer_detail img')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('#offer_detail')).toContainText('Junior IAM à examiner');
  await expect(page.locator('#feedback_form button[type="submit"]')).toBeEnabled();
  await page.keyboard.press('Escape');
  await expect(page.locator('#offer_drawer')).not.toHaveClass(/open/);
  expect(new URL(page.url()).searchParams.has('open')).toBe(false);
});

test('menu mobile modal, clavier et restauration du focus', async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const toggle = page.getByRole('button', { name: 'Ouvrir le menu', exact: true });
  await toggle.click();
  await expect(page.locator('#app_sidebar')).toHaveAttribute('aria-modal', 'true');
  expect(await page.locator('#app_workspace').evaluate((element) => element.inert)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(toggle).toBeFocused();
  expect(await page.locator('#app_workspace').evaluate((element) => element.inert)).toBe(false);
  await toggle.click();
  await page.getByRole('link', { name: 'Vue d’ensemble', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.locator('#app_menu_toggle')).toHaveAttribute('aria-expanded', 'false');
});

test('évaluation : modes URL/texte, charge utile conservée et erreur visible', async ({ page }) => {
  await login(page, 'member', 'member-correct-password');
  await expect(page.locator('#evaluation_text')).not.toBeVisible();
  await page.locator('[data-evaluation-mode="text"]').click();
  await expect(page.locator('#manual_form')).toBeVisible();
  await expect(page.locator('#evaluation_urls')).not.toBeVisible();
  let submitted;
  await page.route(/\/api\/evaluate\/manual$/, async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Erreur synthétique de vérification UI' }) });
  });
  await page.locator('#manual_url').fill('https://jobs.example.test/manual');
  await page.locator('#manual_title').fill('Example role');
  await page.locator('#manual_text').fill('Texte synthétique pour tester uniquement le formulaire. '.repeat(10));
  await page.locator('#manual_form button[type="submit"]').click();
  await expect(page.locator('#manual_status')).toContainText('Erreur synthétique');
  expect(submitted.url).toBe('https://jobs.example.test/manual');
  expect(submitted.title).toBe('Example role');
  expect(submitted.published_at).toBe(null);
  await expect(page.locator('#manual_form button[type="submit"]')).toBeEnabled();
});

test('dashboard indisponible : aucun zéro ou résultat fictif présenté comme réel', async ({ page }) => {
  await login(page);
  await page.route(/\/api\/offers\?/, (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Indisponible pour le test UI' }) }));
  await page.goto('/dashboard');
  await expect(page.locator('#dashboard_total')).toHaveText('Indisponible');
  await expect(page.locator('#dashboard_selection [role="alert"]')).toBeVisible();
  await expect(page.locator('#dashboard_actions')).toContainText('momentanément indisponible');
});

test('préférence thème : stockage désactivé sans bloquer la navigation', async ({ browser }) => {
  const context = await browser.newContext();
  await context.addInitScript(() => { Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('Disabled', 'SecurityError'); } }); });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await login(page);
  await page.getByRole('button', { name: 'Activer le thème sombre' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.goto('/dashboard');
  await expect(page.locator('#dashboard_total')).not.toHaveText('—');
  expect(errors).toEqual([]);
  await context.close();
});

test('sans JavaScript : navigation et panneaux restent accessibles', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await login(page, 'member', 'member-correct-password');
  await expect(page.getByRole('navigation', { name: 'Navigation principale' })).toBeVisible();
  await expect(page.locator('#evaluation_urls')).toBeVisible();
  await expect(page.locator('#evaluation_text')).toBeVisible();
  await expect(page.locator('#script_notice')).toBeVisible();
  await expect(page.locator('#script_notice')).toContainText('JavaScript est indisponible.');
  await context.close();
});

test('vues réelles : responsive des deux thèmes aux seuils CSS', async ({ page }) => {
  test.setTimeout(240_000);
  await login(page);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let checked = 0;
  for (const theme of ['light', 'dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('[data-theme-toggle]').click();
    for (const width of [390, 679, 680, 681, 979, 980, 981, 1179, 1180, 1181, 1280, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      for (const route of ['/dashboard', '/', '/offers', '/profile', '/runs', '/cv', '/applications', '/analytics', '/admin', '/admin/audit', '/admin/diagnostics']) {
        await page.goto(route);
        await page.waitForLoadState('networkidle');
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
        expect(overflow, `${route}, ${theme}, ${width}px`).toBeLessThanOrEqual(1);
        checked += 1;
      }
    }
  }
  expect(errors).toEqual([]);
  console.log(`v3 app layout checks: ${checked}`);
});
