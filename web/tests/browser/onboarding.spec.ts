import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const completionKey = 'elections:onboarding:v1';

async function expectApplicationReady(page: Page) {
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await expect(page.getByTestId('election-map')).toHaveAttribute('data-map-ready', 'true');
}

async function expectSpotlightPlaced(page: Page, mobile: boolean) {
  await expect
    .poll(async () => {
      const target = await page.locator('#results').boundingBox();
      const spotlight = await page.getByTestId('onboarding-spotlight').boundingBox();
      const card = await page.getByTestId('onboarding-card').boundingBox();
      const viewport = page.viewportSize();
      if (!target || !spotlight || !card || !viewport) return false;
      const aligned =
        Math.abs(spotlight.x - Math.max(4, target.x - 6)) < 2 &&
        Math.abs(spotlight.y - Math.max(4, target.y - 6)) < 2;
      const inside =
        card.x >= 0 &&
        card.y >= 0 &&
        card.x + card.width <= viewport.width + 1 &&
        card.y + card.height <= viewport.height + 1;
      const separate = mobile
        ? card.y + card.height < spotlight.y
        : card.x + card.width < spotlight.x;
      return aligned && inside && separate;
    })
    .toBe(true);
}

test('shows on first visit and records completion only after explicit dismissal', async ({
  page,
  isMobile,
}) => {
  await page.goto('./');
  const guide = page.getByTestId('onboarding-guide');
  await expect(guide).toBeVisible();
  await expect(guide).toContainText('Esta escolha muda o mapa');
  await expect(guide).toContainText('votos brancos, nulos ou abstenção');
  await expect(page.getByTestId('onboarding-primary')).toBeFocused();
  await expectSpotlightPlaced(page, isMobile);
  expect(await page.evaluate((key) => localStorage.getItem(key), completionKey)).toBeNull();
  const audit = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(audit.violations).toEqual([]);
  await page.reload();
  await expect(guide).toBeVisible();
  expect(await page.evaluate((key) => localStorage.getItem(key), completionKey)).toBeNull();
  await page.getByRole('button', { name: 'Fechar guia', exact: true }).click();
  await expect(guide).not.toBeVisible();
  await expect(
    page.getByTestId(isMobile ? 'mobile-origin-launcher' : 'origin-augusto_cury'),
  ).toBeFocused();
  expect(await page.evaluate((key) => localStorage.getItem(key), completionKey)).toBe('completed');
  await page.reload();
  await expectApplicationReady(page);
  await expect(guide).not.toBeVisible();
});

test('replays on request and returns keyboard focus to its launcher on Escape or close', async ({
  page,
}) => {
  await page.addInitScript((key) => localStorage.setItem(key, 'completed'), completionKey);
  await page.goto('./');
  await expectApplicationReady(page);
  const replay = page.getByTestId('open-onboarding');
  const guide = page.getByTestId('onboarding-guide');
  await expect(guide).not.toBeVisible();
  await replay.focus();
  await replay.press('Enter');
  await expect(guide).toBeVisible();
  await expect(page.getByTestId('onboarding-primary')).toBeFocused();
  await page.keyboard.press('Tab');
  const focusState = await page.evaluate(() => ({
    browserChrome: document.activeElement === document.body,
    insideGuide: !!document.activeElement?.closest('[data-testid="onboarding-guide"]'),
  }));
  expect(focusState.browserChrome || focusState.insideGuide).toBe(true);
  if (focusState.browserChrome) await page.keyboard.press('Tab');
  await expect(guide.getByRole('button', { name: 'Fechar guia' })).toBeFocused();
  await replay.focus();
  await expect(replay).not.toBeFocused();
  await page.keyboard.press('Escape');
  await expect(guide).not.toBeVisible();
  await expect(replay).toBeFocused();
  await replay.click();
  await page.getByRole('button', { name: 'Fechar guia', exact: true }).click();
  await expect(replay).toBeFocused();
  expect(await page.evaluate((key) => localStorage.getItem(key), completionKey)).toBe('completed');
});

test('continues directly to choosing an origin without changing the selection prematurely', async ({
  page,
  isMobile,
}) => {
  await page.goto('./');
  const guide = page.getByTestId('onboarding-guide');
  await expect(guide).toBeVisible();
  await expect(page.getByTestId('origin-augusto_cury')).toHaveAttribute('aria-pressed', 'true');
  const initialScroll = await page.evaluate(() => window.scrollY);
  await page.getByTestId('onboarding-primary').click();
  await expect(guide).not.toBeVisible();
  if (isMobile) {
    await expect(page.getByTestId('origin-sheet')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Fechar origens' })).toBeFocused();
  } else await expect(page.getByTestId('origin-augusto_cury')).toBeFocused();
  await page.getByTestId('origin-blank').click();
  await expect(page.locator('.map-subtitle')).toContainText('Brancos');
  expect(new URL(page.url()).searchParams.get('origin')).toBe('blank');
  expect(await page.evaluate(() => window.scrollY)).toBe(initialScroll);
  if (isMobile) {
    await expect(page.getByTestId('origin-sheet')).not.toBeVisible();
    await expect(page.getByTestId('mobile-origin-launcher')).toBeFocused();
  }
});

test('remeasures its target across responsive layout changes and respects reduced motion', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('./');
  const guide = page.getByTestId('onboarding-guide');
  await expect(guide).toBeVisible();
  await page.setViewportSize({ width: 320, height: 740 });
  await expect(page.getByTestId('onboarding-card')).toHaveAttribute('data-placement', 'above');
  await expectSpotlightPlaced(page, true);
  await expect(page.getByTestId('onboarding-primary')).toBeFocused();
  await page.setViewportSize({ width: 1366, height: 768 });
  await expect(page.getByTestId('onboarding-card')).toHaveAttribute('data-placement', 'left');
  await expectSpotlightPlaced(page, false);
  await expect(page.getByTestId('onboarding-primary')).toBeFocused();
  expect(
    await page
      .getByTestId('onboarding-card')
      .evaluate((element) => getComputedStyle(element).animationName),
  ).toBe('none');
  await page.keyboard.press('Escape');
  await expect(guide).not.toBeVisible();
  await expect(page.getByTestId('origin-augusto_cury')).toBeFocused();
});

test('remains usable when browser storage is unavailable', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new DOMException('Storage blocked for this test', 'SecurityError');
      },
    });
  });
  await page.goto('./');
  const guide = page.getByTestId('onboarding-guide');
  await expect(guide).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(guide).not.toBeVisible();
  await page.getByTestId('open-onboarding').click();
  await expect(guide).toBeVisible();
  await page.getByRole('button', { name: 'Fechar guia', exact: true }).click();
  await expect(guide).not.toBeVisible();
  await expect(page.getByTestId('open-onboarding')).toBeFocused();
  await page.reload();
  await expect(guide).toBeVisible();
  expect(errors).toEqual([]);
});

test('keeps its introduction and actions visible in a short landscape viewport', async ({
  page,
}) => {
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto('./');
  const guide = page.getByTestId('onboarding-guide');
  const primary = page.getByTestId('onboarding-primary');
  await expect(guide).toBeVisible();
  await expect(primary).toBeFocused();
  await expect(primary).toBeInViewport({ ratio: 0.99 });
  await expect(guide.getByRole('button', { name: 'Fechar guia' })).toBeInViewport({ ratio: 0.99 });
  await expect(guide.getByRole('heading', { name: 'Esta escolha muda o mapa' })).toBeInViewport({
    ratio: 0.99,
  });
  await expectSpotlightPlaced(page, false);
  expect(
    await primary.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return element.contains(
        document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2),
      );
    }),
  ).toBe(true);
  await primary.click();
  await expect(guide).not.toBeVisible();
  await expect(page.getByTestId('origin-augusto_cury')).toBeFocused();
});
