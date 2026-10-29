import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { createHash } from 'node:crypto';
import { gunzipSync, gzipSync } from 'node:zlib';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('elections:onboarding:v1', 'completed');
  });
});

const integerShare = /^(\d{1,3}%|<1%|>99%|—)$/;
const placeId = (page: Page) => new URL(page.url()).searchParams.get('place');

async function openOrigins(page: Page) {
  const launcher = page.getByTestId('mobile-origin-launcher');
  if ((await launcher.isVisible()) && (await launcher.getAttribute('aria-expanded')) !== 'true')
    await launcher.click();
}
async function closeOrigins(page: Page) {
  const close = page.getByRole('button', { name: 'Fechar origens' });
  if (await close.isVisible()) await close.click();
}
async function mapReady(page: Page) {
  await expect(page.getByTestId('election-map')).toHaveAttribute('data-map-ready', 'true');
  await expect(page.getByTestId('election-map')).toHaveAttribute('data-map-locked', 'false');
}
async function search(page: Page, query: string, option: RegExp) {
  await page.getByTestId('geographic-search').fill(query);
  await page.getByRole('option', { name: option }).first().click();
}

type Bundle = {
  children: {
    id: string;
    sectionCount: number;
    electorate: number;
    rows: {
      observed: number;
      estimated: Record<string, number>;
      sensitivity: unknown;
      identificationBounds: Record<string, { min: number; max: number }>;
    }[];
  }[];
  geometry: Record<string, { features: { properties: { id: string } }[] }>;
};

/**
 * Serves a derived copy of the real MG fixture bundle, with a matching manifest descriptor, to
 * exercise rare interface states. The mutation is synthetic and exists only inside the test.
 */
async function serveDerivedState(page: Page, baseURL: string, mutate: (bundle: Bundle) => void) {
  const manifestUrl = new URL('data/manifest.json', baseURL).href;
  const manifest = await (await page.request.get(manifestUrl)).json();
  const descriptor = manifest.resources.states.MG;
  const original = await (
    await page.request.get(new URL(`data/${descriptor.path}`, baseURL).href)
  ).body();
  const bundle = JSON.parse(gunzipSync(original).toString('utf8')) as Bundle;
  mutate(bundle);
  const bytes = gzipSync(Buffer.from(JSON.stringify(bundle)));
  manifest.resources.states.MG = {
    ...descriptor,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
  };
  await page.route('**/data/manifest.json', (route) => route.fulfill({ json: manifest }));
  await page.route(`**/data/${descriptor.path}`, (route) =>
    route.fulfill({ body: bytes, contentType: 'application/octet-stream' }),
  );
}

test('loads a national map and changes origin without downloading a state bundle', async ({
  page,
}) => {
  const stateRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/states/')) stateRequests.push(request.url());
  });
  await page.goto('./');
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await mapReady(page);
  await openOrigins(page);
  await page.getByTestId('origin-blank').click();
  await expect(page.getByTestId('origin-blank')).toHaveAttribute('aria-pressed', 'true');
  expect(new URL(page.url()).searchParams.get('origin')).toBe('blank');
  expect(stateRequests).toEqual([]);
  await openOrigins(page);
  for (const share of await page.locator('.origin-share').allTextContents())
    expect(share).toMatch(integerShare);
  await closeOrigins(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(accessibility.violations).toEqual([]);
});

test('searches a municipality inside its state bundle and restores browser history', async ({
  page,
}) => {
  const stateRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/states/')) stateRequests.push(request.url());
  });
  await page.goto('./');
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await search(page, 'Belo Horizonte', /Belo Horizonte/);
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  expect(placeId(page)).toBe('MG:41238');
  await mapReady(page);
  const crumbs = page.getByRole('navigation', { name: 'Localização selecionada' });
  await expect(crumbs.getByRole('button', { name: 'Minas Gerais' })).toBeVisible();
  await expect(crumbs.locator('[aria-current="location"]')).toHaveText('Belo Horizonte');
  await search(page, 'Betim', /^Betim/);
  await expect(page.getByTestId('place-title')).toHaveText('Betim');
  await mapReady(page);
  expect(stateRequests.filter((url) => url.includes('/states/MG.'))).toHaveLength(1);
  await page.goBack();
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await page.goBack();
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await page.goForward();
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await page.reload();
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await crumbs.getByRole('button', { name: 'Minas Gerais' }).click();
  await expect(page.getByTestId('place-title')).toHaveText('Minas Gerais');
  expect(placeId(page)).toBe('MG');
});

test('opens a shared municipality link, canonicalizes it and reports unknown places', async ({
  page,
}) => {
  await page.goto('./?place=MG%3A41238&origin=renan_santos');
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await expect(page.locator('.map-subtitle')).toContainText('Renan Santos');

  await page.goto('./?place=MG%3A41238&origin=nobody&extra=1');
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await expect.poll(() => new URL(page.url()).search).toBe('?place=MG%3A41238&origin=augusto_cury');

  await page.goto('./?place=MG%3A41238%3Ar%3A18&origin=blank');
  await expect(page.locator('.error-panel')).toContainText('não foi encontrado');
});

test('selects a municipality by clicking the state map and shows integer shares', async ({
  page,
  isMobile,
}) => {
  await page.goto('./?place=MG&origin=augusto_cury');
  await expect(page.getByTestId('place-title')).toHaveText('Minas Gerais');
  await mapReady(page);
  const bounds = (await page.locator('.map-canvas').boundingBox())!;
  const center = { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
  let tooltipName: string | null = null;
  if (!isMobile) {
    await page.mouse.move(center.x - 3, center.y);
    await page.mouse.move(center.x, center.y);
    const tooltip = page.locator('.map-tooltip');
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText(/Lula (\d{1,3}%|<1%|>99%) · Flávio (\d{1,3}%|<1%|>99%)/);
    tooltipName = await tooltip.locator('strong').textContent();
  }
  if (isMobile) await page.touchscreen.tap(center.x, center.y);
  else await page.mouse.click(center.x, center.y);
  await expect.poll(() => placeId(page)).toMatch(/^MG:\d+$/);
  await expect(page.getByTestId('place-title')).not.toHaveText('Minas Gerais');
  if (tooltipName) await expect(page.getByTestId('place-title')).toHaveText(tooltipName);
  await mapReady(page);
  await expect(
    page
      .getByRole('navigation', { name: 'Localização selecionada' })
      .getByRole('button', { name: 'Minas Gerais' }),
  ).toBeVisible();
});

test('explains uncertainty with model-provided text and preserves all five destinations', async ({
  page,
  baseURL,
}) => {
  const manifest = await (
    await page.request.get(new URL('data/manifest.json', baseURL).href)
  ).json();
  await page.goto('./?place=BR&origin=blank');
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await openOrigins(page);
  await page.getByTestId('open-details').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId('sensitivity-description')).toHaveText(
    manifest.model.sensitivityDescription,
  );
  await expect(dialog.getByTestId('bounds-description')).toHaveText(
    manifest.model.boundsDescription,
  );
  await expect(dialog).toContainText('Não são intervalos de confiança');
  await expect(page.getByRole('row')).toHaveCount(6);
  for (const share of await dialog.locator('tbody td:nth-child(2)').allTextContents())
    expect(share).toMatch(integerShare);
  for (const testId of ['sensitivity-range', 'identification-bounds'])
    for (const range of await dialog.getByTestId(testId).locator('strong').allTextContents())
      expect(range).toMatch(/^(\d{1,3}%|<1%|>99%) – (\d{1,3}%|<1%|>99%)$/);
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  await page.getByRole('button', { name: 'Fechar explicação' }).click();
  await openOrigins(page);
  await page.getByTestId('origin-null').click();
  await openOrigins(page);
  await page.getByTestId('open-details').click();
  await expect(dialog).toContainText('Uma faixa conjunta não foi calculada');
  await expect(dialog.getByTestId('sensitivity-range')).toHaveCount(0);
  await expect(dialog.getByTestId('identification-bounds')).toHaveCount(0);
  await expect(dialog.getByTestId('bounds-unavailable')).toBeVisible();
  await page.getByRole('button', { name: 'Fechar explicação' }).click();

  await page.goto('./?place=MG%3A41238&origin=augusto_cury');
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await openOrigins(page);
  await page.getByTestId('open-details').click();
  await expect(dialog.getByTestId('identification-bounds')).toBeVisible();
  await expect(dialog.getByTestId('sensitivity-range')).toBeVisible();
  await expect(dialog.getByTestId('detail-small-base-note')).toHaveCount(0);
});

test('methodology names the municipality as the finest level', async ({ page }) => {
  await page.goto('./');
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await page.getByTestId('open-method').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByTestId('municipality-method')).toContainText('não a residência');
  await expect(dialog.getByTestId('municipality-method')).toContainText(
    'nível mais detalhado publicado',
  );
  await expect(dialog).not.toContainText(/bairro|não localizados|camada/i);
});

test('marks a small origin base in the panel, sheet, map legend and detail', async ({
  page,
  isMobile,
}) => {
  // Betim has 90 first-round Hertz Dias voters in the real data.
  await page.goto('./?place=MG%3A41335&origin=hertz_dias');
  await expect(page.getByTestId('place-title')).toHaveText('Betim');
  await mapReady(page);
  const note =
    'Base pequena: menos de 100 eleitores desta origem aqui. A estimativa reflete sobretudo o padrão regional do modelo.';
  if (isMobile) {
    await expect(page.getByTestId('launcher-small-base')).toBeVisible();
    await expect(page.getByTestId('mobile-origin-launcher')).toHaveAttribute(
      'aria-label',
      /Base pequena/,
    );
    await openOrigins(page);
    await expect(page.getByTestId('origin-sheet').getByTestId('small-base-note')).toHaveText(note);
    await closeOrigins(page);
  } else await expect(page.getByTestId('small-base-note')).toHaveText(note);
  await expect(page.getByTestId('small-base-key')).toBeVisible();
  await openOrigins(page);
  await page.getByTestId('open-details').click();
  await expect(page.getByTestId('detail-small-base-note')).toHaveText(note);
  await page.getByRole('button', { name: 'Fechar explicação' }).click();

  await openOrigins(page);
  await page.getByTestId('origin-augusto_cury').click();
  await expect(page.locator('.map-subtitle')).toContainText('Augusto Cury');
  await expect(page.getByTestId('small-base-note')).toHaveCount(0);
  await expect(page.getByTestId('launcher-small-base')).toHaveCount(0);
});

test('keeps an absent origin distinct from a small base', async ({ page }) => {
  // Araxá has no first-round Rui Costa Pimenta voters in the real data.
  await page.goto('./?place=MG%3A40797&origin=rui_costa_pimenta');
  await expect(page.getByTestId('place-title')).toHaveText('Araxá');
  await openOrigins(page);
  await expect(page.getByTestId('origin-rui_costa_pimenta')).toContainText(
    'Origem ausente nesta seleção',
  );
  await expect(page.getByTestId('small-base-note')).toHaveCount(0);
  await expect(page.getByTestId('launcher-small-base')).toHaveCount(0);
  await page.getByTestId('open-details').click();
  await expect(page.getByTestId('detail-small-base-note')).toHaveCount(0);
  await expect(page.getByTestId('bounds-unavailable')).toBeVisible();
});

test('keeps a municipality without geometry listed and selectable', async ({ page, baseURL }) => {
  await serveDerivedState(page, baseURL!, (bundle) => {
    const layer = bundle.geometry.municipalities;
    layer.features = layer.features.filter((feature) => feature.properties.id !== 'MG:41238');
  });
  await page.goto('./?place=MG&origin=blank');
  await expect(page.getByTestId('place-title')).toHaveText('Minas Gerais');
  await mapReady(page);
  const unmapped = page.getByTestId('unmapped-places');
  await unmapped.getByRole('button', { name: 'Belo Horizonte · fora do mapa' }).click();
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  expect(placeId(page)).toBe('MG:41238');
  await expect(page.getByTestId('no-geometry-note')).toContainText('Belo Horizonte');
  await openOrigins(page);
  await expect(page.getByTestId('origin-blank')).toHaveAttribute('aria-pressed', 'true');
  await closeOrigins(page);
  await search(page, 'Betim', /^Betim/);
  await expect(page.getByTestId('place-title')).toHaveText('Betim');
  await expect(page.getByTestId('no-geometry-note')).toHaveCount(0);
  await search(page, 'Belo Horizonte', /Belo Horizonte/);
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await expect(page.getByTestId('no-geometry-note')).toBeVisible();
});

test('returns through geographic parents when a state has no polygons', async ({
  page,
  baseURL,
}) => {
  // Remove geometry only in a derived test copy; all counts still come from the real MG fixture.
  await serveDerivedState(page, baseURL!, (bundle) => {
    bundle.geometry.municipalities.features = [];
  });
  await page.goto('./?place=MG%3A41238&origin=blank');
  await expect(page.getByTestId('place-title')).toHaveText('Belo Horizonte');
  await mapReady(page);
  await expect(page.getByTestId('map-empty')).toContainText('Sem geometria disponível');
  await expect(page.getByRole('button', { name: 'Aproximar mapa', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Reenquadrar mapa', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Afastar mapa', exact: true }).click();
  await expect(page.getByTestId('place-title')).toHaveText('Minas Gerais');
  await mapReady(page);
  expect(placeId(page)).toBe('MG');
  await page.getByRole('button', { name: 'Afastar mapa', exact: true }).click();
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await mapReady(page);
  expect(placeId(page)).toBe('BR');
  expect(new URL(page.url()).searchParams.get('origin')).toBe('blank');
});

test('distinguishes an area with no associated sections from an absent origin', async ({
  page,
  baseURL,
}) => {
  await serveDerivedState(page, baseURL!, (bundle) => {
    const place = bundle.children.find((child) => child.id === 'MG:40010')!;
    place.sectionCount = 0;
    place.electorate = 0;
    for (const row of place.rows) {
      row.observed = 0;
      for (const key of Object.keys(row.estimated)) row.estimated[key] = 0;
      row.sensitivity = null;
      row.identificationBounds = { lula: { min: 0, max: 0 }, flavio: { min: 0, max: 0 } };
    }
  });
  await page.goto('./?place=MG%3A40010&origin=augusto_cury');
  await expect(page.getByTestId('place-title')).toHaveText('Abadia dos Dourados');
  await openOrigins(page);
  await expect(page.getByTestId('no-sections-notice')).toContainText(
    'Sem seções de votação associadas',
  );
  await expect(page.getByTestId('origin-augusto_cury')).toContainText('Sem seções associadas');
  await expect(page.getByTestId('origin-augusto_cury')).not.toContainText('Origem ausente');
  await expect(page.getByTestId('small-base-note')).toHaveCount(0);
  await page.getByTestId('open-details').click();
  await expect(page.getByRole('dialog')).toContainText('sem base associada');
  await expect(page.locator('tbody td:nth-child(3)')).toHaveText(['—', '—', '—', '—', '—']);
  await page.getByRole('button', { name: 'Fechar explicação' }).click();
  await expect(page.locator('.no-sections-key')).toBeVisible();
});

test('lists foreign localities without polygons and returns through their parents', async ({
  page,
  baseURL,
}) => {
  const manifest = await (
    await page.request.get(new URL('data/manifest.json', baseURL).href)
  ).json();
  test.skip(!manifest.resources.states.ZZ, 'Voters abroad are outside the fixture.');
  await page.goto('./?place=ZZ&origin=blank');
  await expect(page.getByTestId('place-title')).toHaveText('Exterior');
  const empty = page.getByTestId('map-empty');
  await expect(empty).toContainText('Localidades no exterior não têm limites no mapa');
  const first = empty.getByRole('listitem').first().getByRole('button');
  const name = (await first.textContent())!;
  await first.click();
  await expect(page.getByTestId('place-title')).toHaveText(name);
  expect(placeId(page)).toMatch(/^ZZ:\d+$/);
  await expect(
    page
      .getByRole('navigation', { name: 'Localização selecionada' })
      .locator('[aria-current="location"]'),
  ).toHaveText(name);
  await mapReady(page);
  await expect(page.getByRole('button', { name: 'Aproximar mapa', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Reenquadrar mapa', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Afastar mapa', exact: true }).click();
  await expect(page.getByTestId('place-title')).toHaveText('Exterior');
  await mapReady(page);
  expect(placeId(page)).toBe('ZZ');
  await page.getByRole('button', { name: 'Afastar mapa', exact: true }).click();
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  await mapReady(page);
  expect(placeId(page)).toBe('BR');
  expect(new URL(page.url()).searchParams.get('origin')).toBe('blank');
});

test('keeps keyboard search choices visible without scrolling the page', async ({ page }) => {
  await page.goto('./');
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  const search = page.getByTestId('geographic-search');
  await search.fill('São');
  await expect(page.getByRole('option')).toHaveCount(10);
  const initialScroll = await page.evaluate(() => window.scrollY);
  for (let index = 0; index < 9; index++) await search.press('ArrowDown');
  await expect
    .poll(async () => {
      const active = await page.getByRole('option', { selected: true }).boundingBox();
      const list = await page.getByRole('listbox').boundingBox();
      return (
        !!active && !!list && active.y >= list.y && active.y + active.height <= list.y + list.height
      );
    })
    .toBe(true);
  expect(await page.evaluate(() => window.scrollY)).toBe(initialScroll);
});

test('opens and closes the mobile origin sheet without losing the map or keyboard focus', async ({
  page,
  isMobile,
}) => {
  await page.goto('./');
  await expect(page.getByTestId('place-title')).toHaveText('Brasil');
  if (!isMobile) {
    await expect(page.getByTestId('mobile-origin-launcher')).toHaveCount(0);
    await expect(page.getByTestId('origin-abstention')).toBeVisible();
    return;
  }
  const launcher = page.getByTestId('mobile-origin-launcher');
  const sheet = page.getByTestId('origin-sheet');
  const initialScroll = await page.evaluate(() => window.scrollY);
  await launcher.focus();
  await launcher.press('Enter');
  await expect(sheet).toBeVisible();
  await expect(sheet.locator('button[data-testid^="origin-"]')).toHaveCount(13);
  await expect(sheet.locator('button[aria-pressed="true"]')).toHaveCount(1);
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  await page.getByTestId('origin-abstention').focus();
  await page.getByTestId('origin-abstention').press('Enter');
  await expect(sheet).not.toBeVisible();
  await expect(launcher).toBeFocused();
  await expect(launcher).toContainText('Abstenção');
  expect(await page.evaluate(() => window.scrollY)).toBe(initialScroll);
  await expect(page.getByTestId('election-map')).toBeVisible();
  await launcher.click();
  await page.getByRole('button', { name: 'Fechar origens' }).click();
  await expect(sheet).not.toBeVisible();
  await expect(launcher).toBeFocused();
});
