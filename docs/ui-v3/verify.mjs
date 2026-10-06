import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium, expect } from '@playwright/test';

const root = path.dirname(fileURLToPath(import.meta.url));
const output = path.resolve(root, '../../test-results/ui-v3-preview');
const files = { '/': ['index.html', 'text/html'], '/index.html': ['index.html', 'text/html'], '/styles.css': ['styles.css', 'text/css'], '/preview.js': ['preview.js', 'text/javascript'] };
const server = createServer(async (request, response) => {
  const name = new URL(request.url, 'http://localhost').pathname;
  const entry = files[name];
  if (!entry) { response.writeHead(404); response.end('Not found'); return; }
  try { response.writeHead(200, { 'Content-Type': entry[1] + '; charset=utf-8', 'Cache-Control': 'no-store' }); response.end(await readFile(path.join(root, entry[0]))); }
  catch (_) { response.writeHead(500); response.end('Static preview unavailable'); }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}/`;
let browser;
const checks = [];
const errors = [];
const outgoing = [];
let layouts = 0;
const check = async (name, fn) => { await fn(); checks.push(name); console.log('PASS', name); };
try {
  await mkdir(output, { recursive: true });
  browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (!request.url().startsWith(base)) outgoing.push(request.url()); });
  await page.goto(base);
  await check('Accueil et données explicitement fictives', async () => {
    await expect(page.getByRole('heading', { name: 'Bonjour Camille.' })).toBeVisible();
    await expect(page.locator('.demo-banner')).toContainText('Données fictives');
    await expect(page.locator('.kpi')).toHaveCount(3);
  });
  await page.goto(base + '#offers');
  await check('Liste, recherche, filtre et état vide', async () => {
    await expect(page.locator('.offer-card')).toHaveCount(4);
    await page.getByLabel('Rechercher').fill('horizon');
    await expect(page.locator('.offer-card')).toHaveCount(1);
    await page.getByLabel('Rechercher').fill('');
    await page.getByLabel('Décision', { exact: false }).selectOption('review');
    await expect(page.locator('.offer-card')).toHaveCount(1);
    await page.getByLabel('Rechercher').fill('aucune correspondance');
    await expect(page.locator('.empty')).toBeVisible();
    await expect(page.locator('#result_count')).toContainText('0 offre');
    await page.getByLabel('Rechercher').fill('');
    await page.getByLabel('Décision', { exact: false }).selectOption('');
    await page.getByLabel('Trier').selectOption('score');
    await expect(page.locator('.offer-card').first()).toContainText('Atelier Atlas');
  });
  await check('Détail : verdict, confiance, portes et preuve distincts', async () => {
    await page.locator('.offer-card').first().click();
    await expect(page.getByRole('heading', { name: 'Analyste données', exact: true })).toBeVisible();
    await expect(page.locator('blockquote')).toContainText('Deux ans d’expérience');
    await expect(page.getByRole('heading', { name: 'Conditions vérifiées' })).toBeVisible();
    await expect(page.getByText('Confiance modèle fictive', { exact: false })).toBeVisible();
    await page.getByText('Lire le texte source de l’exemple', { exact: true }).click();
    const quote = await page.locator('blockquote').innerText();
    assert((await page.locator('details > p').innerText()).includes(quote));
  });
  await check('Dialogue au clavier et retour du focus', async () => {
    const trigger = page.getByRole('button', { name: 'Comment lire l’analyse ?' });
    await trigger.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).not.toBeVisible();
    await expect(trigger).toBeFocused();
  });
  await check('Exclusion sans score et revue linguistique', async () => {
    await page.goto(base + '#detail/meridian');
    await expect(page.locator('.score-display')).toContainText('—');
    await expect(page.locator('.gate-row').filter({ hasText: 'Expérience' })).toContainText('Bloquant');
    await page.goto(base + '#detail/horizon');
    await expect(page.locator('.gate-row').filter({ hasText: 'Langues' })).toContainText('À vérifier');
  });
  await check('Profil guidé, aperçu et données échappées', async () => {
    await page.goto(base + '#profile');
    await page.getByLabel('Poste visé', { exact: true }).fill('<img src=x onerror=alert(1)>');
    await expect(page.locator('#profile_summary')).toContainText('<img src=x onerror=alert(1)>');
    assert.equal(await page.locator('#profile_summary img').count(), 0);
    await page.getByLabel('Poste visé', { exact: true }).fill('Analyste données');
    await page.getByRole('button', { name: '2 · Ma recherche' }).click();
    await page.getByLabel('Lieux acceptés', { exact: false }).fill('France\nBerlin, DE');
    await expect(page.locator('#profile_summary')).toContainText('Berlin, DE');
    await page.getByLabel('Indépendant', { exact: true }).check();
    await expect(page.locator('#profile_summary')).toContainText('Indépendant');
    await page.getByRole('button', { name: '3 · Règles & confirmation' }).click();
    await page.getByRole('button', { name: 'Tester l’enregistrement' }).click();
    await expect(page.locator('#profile_feedback')).toContainText('aucune donnée enregistrée');
    await page.reload();
    await expect(page.locator('#profile_summary')).not.toContainText('Berlin, DE');
  });
  await check('Analyse simulée sans appel API ni résultat attribué aux URLs', async () => {
    await page.goto(base + '#evaluate');
    await page.getByRole('button', { name: 'Simuler le parcours' }).click();
    await expect(page.locator('#evaluation_feedback')).toContainText('ne correspond pas aux liens');
    await page.getByLabel('URLs à analyser').fill('pas une URL');
    await page.getByRole('button', { name: 'Simuler le parcours' }).click();
    await expect(page.locator('#evaluation_feedback')).toContainText('Saisissez une URL');
  });
  await check('Thèmes clair/sombre et persistance du thème', async () => {
    await page.getByRole('button', { name: 'Activer le thème sombre' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.getByRole('button', { name: 'Activer le thème clair' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });
  await check('Menu mobile au clavier et navigation', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Ouvrir le menu' }).click();
    await expect(page.locator('#menu_toggle')).toHaveAttribute('aria-expanded', 'true');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Ouvrir le menu' })).toBeFocused();
    await page.getByRole('button', { name: 'Ouvrir le menu' }).click();
    await page.getByRole('link', { name: 'Mes offres' }).click();
    await expect(page.getByRole('heading', { name: 'Mes offres' })).toBeVisible();
    await expect(page.locator('#menu_toggle')).toHaveAttribute('aria-expanded', 'false');
  });
  const views = [ ['home', null], ['offers', null], ['detail/atlas', null], ['detail/horizon', null], ['detail/meridian', null], ['profile', '1 · Mon expérience'], ['profile', '2 · Ma recherche'], ['profile', '3 · Règles & confirmation'], ['evaluate', null] ];
  await check('Responsive : aucun débordement horizontal sur les vues et thèmes', async () => {
    for (const theme of ['light', 'dark']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme_toggle').click();
      for (const width of [390, 680, 759, 760, 761, 768, 900, 1099, 1100, 1101, 1280, 1440]) {
        await page.setViewportSize({ width, height: 1000 });
        for (const [view, tab] of views) {
          await page.goto(base + '#' + view);
          if (tab) await page.getByRole('button', { name: tab, exact: true }).click();
          await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)));
          const size = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, viewport: innerWidth }));
          assert(size.scroll <= size.viewport, `${theme} ${width}px ${view} ${tab}: ${JSON.stringify(size)}`);
          layouts += 1;
        }
      }
    }
  });
  await check('URL inconnue, historique navigateur et absence de requêtes sortantes', async () => {
    await page.goto(base + '#detail/inexistant');
    await expect(page.getByRole('heading', { name: 'Cette offre n’existe pas.' })).toBeVisible();
    await page.getByRole('link', { name: 'Retour aux offres', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Mes offres' })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('heading', { name: 'Cette offre n’existe pas.' })).toBeVisible();
    assert.deepEqual(errors, []);
    assert.deepEqual(outgoing, []);
  });
  for (const [name, view, width, theme] of [ ['home-desktop', 'home', 1440, 'light'], ['offers-desktop', 'offers', 1440, 'light'], ['detail-review', 'detail/horizon', 1440, 'light'], ['profile-desktop', 'profile', 1440, 'light'], ['offers-mobile', 'offers', 390, 'light'], ['home-dark', 'home', 1440, 'dark'] ]) {
    await page.setViewportSize({ width, height: width < 700 ? 844 : 1000 });
    await page.goto(base + '#' + view);
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme_toggle').click();
    await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
  }
  const result = { scenarios: checks.length, layout_checks: layouts, passed: checks, javascript_errors: errors, external_requests: outgoing, screenshots: output };
  await writeFile(path.join(output, 'verification.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
