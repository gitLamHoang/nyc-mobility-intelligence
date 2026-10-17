import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseDemo } from './data.ts';
import { readView, viewURL } from './view.ts';
const d = parseDemo(
  JSON.parse(readFileSync(new URL('../public/data/demo.json', import.meta.url), 'utf8')),
);
test('shared URL restores every view setting using a stable zone ID', () => {
  const selected = d.zones.findIndex((z) => z.borough === 'Queens');
  const view = {
    hour: 47,
    borough: 'Queens',
    model: 'previous_week_168h',
    metric: 'error',
    selected,
  } as const;
  const original = new URL('https://example.com/nyc-mobility-intelligence/?ref=portfolio#explorer');
  const url = viewURL(original, d, view);
  assert.equal(url.searchParams.get('zone'), String(d.zones[selected]!.id));
  assert.deepEqual(readView(url, d), view);
  assert.equal(url.pathname, original.pathname);
  assert.equal(url.searchParams.get('ref'), 'portfolio');
  assert.equal(url.hash, '#explorer');
  assert.equal(original.searchParams.has('hour'), false);
});
test('missing or malformed URL settings fall back to usable defaults', () => {
  const defaults = readView(new URL('https://example.com/'), d);
  assert.equal(defaults.hour, 16);
  assert.equal(d.zones[defaults.selected]!.name, 'Midtown Center');
  for (const hour of ['', '-1', '48', '1.5', 'Infinity', 'NaN', '1e1']) {
    const url = new URL('https://example.com/?borough=Unknown&model=toString&metric=bad&zone=9999');
    url.searchParams.set('hour', hour);
    const view = readView(url, d);
    assert.equal(view.hour, defaults.hour);
    assert.equal(view.borough, defaults.borough);
    assert.equal(view.model, defaults.model);
    assert.equal(view.metric, defaults.metric);
    assert.ok(view.selected >= 0);
  }
  assert.equal(readView(new URL('https://example.com/?hour=0'), d).hour, 0);
});
test('a shared zone outside the selected borough falls back inside that borough', () => {
  const other = d.zones.find((z) => z.borough !== 'Brooklyn')!;
  const view = readView(new URL(`https://example.com/?borough=Brooklyn&zone=${other.id}`), d);
  assert.equal(d.zones[view.selected]!.borough, 'Brooklyn');
});
