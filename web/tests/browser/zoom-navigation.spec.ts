import { expect, test, type Page } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('elections:onboarding:v1', 'completed');
  });
});

const map = (page: Page) => page.getByTestId('election-map');
const placeId = (page: Page) => new URL(page.url()).searchParams.get('place') || 'BR';

async function ready(page: Page) {
  await expect(map(page)).toHaveAttribute('data-map-ready', 'true');
  await expect(map(page)).toHaveAttribute('data-map-locked', 'false');
}

async function pointAtMinasGerais(page: Page) {
  const label = await page.locator('.state-label').filter({ hasText: /^MG$/ }).boundingBox();
  expect(label).not.toBeNull();
  await page.mouse.move(label!.x + label!.width / 2, label!.y + label!.height / 2);
}

async function zoomUntil(page: Page, target: (id: string) => boolean, delta: number) {
  for (let attempt = 0; attempt < 10 && !target(placeId(page)); attempt++) {
    await ready(page);
    await page.mouse.wheel(0, delta);
    // Wheel bursts need a quiet interval to count as a fresh gesture after a transition.
    await page.waitForTimeout(350);
  }
  await expect.poll(() => target(placeId(page))).toBe(true);
  await ready(page);
}

test('wheel enters a state and zoom-out stops at a centered national view', async ({ page }) => {
  await page.goto('./?origin=blank');
  await ready(page);
  await pointAtMinasGerais(page);
  await zoomUntil(page, (id) => id === 'MG', -3000);
  await expect(page.getByTestId('place-title')).toHaveText('Minas Gerais');

  await page.getByRole('button', { name: 'Afastar mapa', exact: true }).click();
  await expect.poll(() => placeId(page)).toBe('BR');
  await ready(page);
  const bounds = (await map(page).boundingBox())!;
  await page.mouse.move(bounds.x + 40, bounds.y + 40);
  for (let attempt = 0; attempt < 8; attempt++) await page.mouse.wheel(0, 100_000);
  await ready(page);
  await expect
    .poll(async () => {
      const zoom = Number(await map(page).getAttribute('data-map-zoom'));
      const minimum = Number(await map(page).getAttribute('data-map-min-zoom'));
      return Math.abs(zoom - minimum);
    })
    .toBeLessThan(0.002);
  const clippedLabels = await map(page).evaluate((element) => {
    const viewport = element.getBoundingClientRect();
    return [...element.querySelectorAll('.state-label')].filter((label) => {
      const box = label.getBoundingClientRect();
      return (
        box.left < viewport.left ||
        box.right > viewport.right ||
        box.top < viewport.top ||
        box.bottom > viewport.bottom
      );
    }).length;
  });
  expect(clippedLabels).toBe(0);
  expect(new URL(page.url()).searchParams.get('origin')).toBe('blank');
  await expect(page.getByRole('button', { name: 'Afastar mapa', exact: true })).toBeDisabled();
});

test('a fresh wheel gesture enters a municipality and minus returns one level', async ({
  page,
}) => {
  const stateRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/states/')) stateRequests.push(request.url());
  });
  await page.goto('./?origin=abstention');
  await ready(page);
  await pointAtMinasGerais(page);
  await zoomUntil(page, (id) => id === 'MG', -3000);
  await zoomUntil(page, (id) => /^MG:\d+$/.test(id), -3000);
  const municipality = placeId(page);
  await expect(page.getByTestId('place-title')).not.toHaveText('Minas Gerais');
  // The municipality is a child of the already loaded state bundle.
  expect(stateRequests).toHaveLength(1);
  const zoom = Number(await map(page).getAttribute('data-map-zoom'));
  const maximum = Number(await map(page).getAttribute('data-map-max-zoom'));
  for (let attempt = 0; attempt < 6; attempt++) await page.mouse.wheel(0, -3000);
  await ready(page);
  expect(placeId(page)).toBe(municipality);
  // The finest level has an upper zoom bound instead of a further geographic stage.
  expect(Number.isFinite(maximum)).toBe(true);
  expect(Number(await map(page).getAttribute('data-map-zoom'))).toBeLessThanOrEqual(
    maximum + 0.002,
  );
  expect(Number(await map(page).getAttribute('data-map-zoom'))).toBeGreaterThanOrEqual(zoom);
  await page.getByRole('button', { name: 'Reenquadrar mapa', exact: true }).click();
  await ready(page);
  expect(placeId(page)).toBe(municipality);
  await page.getByRole('button', { name: 'Afastar mapa', exact: true }).click();
  await expect.poll(() => placeId(page)).toBe('MG');
  await ready(page);
  expect(new URL(page.url()).searchParams.get('origin')).toBe('abstention');
  await page.goBack();
  await ready(page);
  await expect.poll(() => placeId(page)).toBe(municipality);
});

test('delayed state loading locks the camera and a later search can cancel it', async ({
  page,
}) => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  let requests = 0;
  await page.route('**/data/states/MG.json.bin', async (route) => {
    requests++;
    await held;
    await route.continue().catch(() => undefined);
  });
  try {
    await page.goto('./?origin=blank');
    await ready(page);
    await pointAtMinasGerais(page);
    for (let attempt = 0; attempt < 8 && requests === 0; attempt++) {
      await page.mouse.wheel(0, -3000);
      await page.waitForTimeout(350);
    }
    await expect.poll(() => requests).toBe(1);
    await expect(map(page)).toHaveAttribute('data-map-locked', 'true');
    const initialZoom = await map(page).getAttribute('data-map-zoom');
    for (let attempt = 0; attempt < 8; attempt++) await page.mouse.wheel(0, -20_000);
    for (let attempt = 0; attempt < 4; attempt++) await page.mouse.wheel(0, 20_000);
    const plus = page.getByRole('button', { name: 'Aproximar mapa', exact: true });
    await expect(plus).toBeDisabled();
    const bounds = (await plus.boundingBox())!;
    for (let attempt = 0; attempt < 5; attempt++)
      await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await expect(map(page)).toHaveAttribute('data-map-zoom', initialZoom!);
    await expect(map(page)).toHaveAttribute('data-map-locked', 'true');
    expect(requests).toBe(1);

    // Municipalities live in the held state bundle, so cancel by searching another bundle.
    await page.getByTestId('geographic-search').fill('Brasil');
    await page.getByRole('option', { name: /inclui exterior/ }).click();
    await expect.poll(() => placeId(page)).toBe('BR');
    await expect(page.getByTestId('place-title')).toHaveText('Brasil');
    await ready(page);
    const nationalZoom = await map(page).getAttribute('data-map-zoom');
    release();
    // Allow the deliberately stale response to complete before testing selection stability.
    await page.waitForTimeout(500);
    expect(placeId(page)).toBe('BR');
    expect(new URL(page.url()).searchParams.get('origin')).toBe('blank');
    await expect(map(page)).toHaveAttribute('data-map-zoom', nationalZoom!);
    await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  } finally {
    release();
  }
});

test('a failed state transition unlocks the rendered map and remains retryable', async ({
  page,
}) => {
  let fail = true;
  let requests = 0;
  await page.route('**/data/states/MG.json.bin', async (route) => {
    requests++;
    if (fail) await route.fulfill({ status: 500, body: 'Temporary test failure' });
    else await route.continue();
  });
  await page.goto('./?origin=blank');
  await ready(page);
  await pointAtMinasGerais(page);
  await zoomUntil(page, (id) => id === 'MG', -3000);
  await expect(page.getByRole('alert')).toContainText('(500)');
  await expect(page.locator('.map-transition-status')).toHaveCount(0);
  expect(requests).toBe(1);

  // The failed gesture must not leave a pending transition that blocks the minus control.
  await page.getByRole('button', { name: 'Afastar mapa', exact: true }).click();
  await expect.poll(() => placeId(page)).toBe('BR');
  await ready(page);
  await expect(page.getByRole('alert')).toHaveCount(0);

  await page.getByTestId('geographic-search').fill('Minas Gerais');
  await page.getByRole('option', { name: /Minas Gerais/ }).click();
  await expect(page.getByRole('alert')).toContainText('(500)');
  await ready(page);
  expect(requests).toBe(2);
  fail = false;
  await page.getByRole('button', { name: 'Tentar novamente', exact: true }).click();
  await expect(page.getByTestId('place-title')).toHaveText('Minas Gerais');
  await ready(page);
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(requests).toBe(3);
  expect(new URL(page.url()).searchParams.get('origin')).toBe('blank');
});
