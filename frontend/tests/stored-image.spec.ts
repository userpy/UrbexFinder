import { test, expect } from '@playwright/test';

test('source image waits for storage, retries locally and never requests origin', async ({ page }) => {
  const digest = 'a'.repeat(64);
  let requests = 0;
  let externalImages = 0;
  page.on('request', request => {
    if (request.resourceType() === 'image' && new URL(request.url()).hostname !== 'localhost') externalImages++;
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/source-images/${digest}`) {
      requests++;
      return requests === 1
        ? route.fulfill({ status: 503, headers: { 'Retry-After': '3' }, body: 'pending' })
        : route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64') });
    }
    if (path === '/api/places/1') return route.fulfill({ json: {
      id: 1, name: 'Тест хранилища', latitude: 55.3, longitude: 37.7, region: 'Москва',
      description: '', category_id: 1, condition: 'unknown', access: 'unknown', status: 'published',
    } });
    if (path === '/api/places/1/source-photos') return route.fulfill({ json: {
      items: [{ image_url: `/api/source-images/${digest}`, source_url: 'https://yandex.ru/maps/org/test/123/', title: 'Фото', original_image_url: 'https://avatars.mds.yandex.net/original.jpg' }], total: 1,
    } });
    if (path === '/api/auth/me') return route.fulfill({ json: { user: null, csrf: null } });
    if (path === '/api/categories') return route.fulfill({ json: { items: [], total: 0 } });
    if (path === '/api/map') return route.fulfill({ json: { type: 'FeatureCollection', features: [] } });
    return route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.goto('/?place=1');
  const image = page.locator(`img[src^="/api/source-images/${digest}"]`).first();
  await expect(page.getByText('Загрузка фотографии…').first()).toBeVisible();
  await expect(image).toBeVisible({ timeout: 12000 });
  expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);
  expect(requests).toBeGreaterThanOrEqual(2);
  expect(externalImages).toBe(0);
});

test('source gallery recovers from a temporary failure after the API cooldown', async ({ page }) => {
  let requests = 0;
  await page.clock.install();
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/places/1') return route.fulfill({ json: {
      id: 1, name: 'Лагерь Слава', latitude: 55.8, longitude: 37.0,
      description: '', category_id: 1, status: 'published',
    } });
    if (path === '/api/places/1/source-photos') {
      requests++;
      return requests === 1
        ? route.fulfill({ status: 502, json: { detail: 'Источник недоступен' } })
        : route.fulfill({ json: { items: [{ image_url: '/api/source-images/' + 'a'.repeat(64),
            source_url: 'https://vk.com/album-97053640_272512036', title: 'Фото' }], total: 1 } });
    }
    if (path === '/api/auth/me') return route.fulfill({ json: { user: null, csrf: null } });
    if (path === '/api/map') return route.fulfill({ json: { type: 'FeatureCollection', features: [] } });
    return route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.goto('/?place=1');
  await expect(page.getByText('Фото источника временно недоступны', { exact: true }).first()).toBeVisible();
  await page.clock.fastForward(29_000);
  expect(requests).toBe(1);
  await page.clock.fastForward(2_000);
  await expect(page.locator('.gallery-total')).toHaveText('1 фото');
  expect(requests).toBe(2);
});
