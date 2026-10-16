import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseDemo, zoneIndices, summarize, forecastMisses, color } from './data.ts';
const raw = JSON.parse(readFileSync(new URL('../public/data/demo.json', import.meta.url), 'utf8'));
test('published export has complete aligned real observations', () => {
  const d = parseDemo(raw);
  assert.equal(d.zones.length, 262);
  assert.equal(d.hours.length, 48);
  assert.equal(d.hours[0]!.time, '2026-04-07T04:00:00+00:00');
  const parts = [...new Set(d.zones.map((z) => z.borough))].flatMap((b) => zoneIndices(d, b));
  assert.equal(new Set(parts).size, 262);
  const all = summarize(d, 0, zoneIndices(d, 'All boroughs'), 'previous_week_168h');
  assert.ok(all.actual > 0 && all.forecast > 0 && all.mae >= 0);
});
test('aggregation uses per-zone absolute error, not aggregate cancellation', () => {
  const d = structuredClone(raw);
  d.hours[0].values = d.hours[0].values.map(() => [0, 0, 0, 0]);
  d.hours[0].values[0] = [10, 5, 2, 0];
  d.hours[0].values[1] = [0, 5, 2, 0];
  assert.deepEqual(summarize(d, 0, [0, 1], 'hist_gradient_boosting'), {
    actual: 10,
    forecast: 10,
    mae: 5,
  });
});
test('rejects corrupt, unaligned, or non-finite exports', () => {
  for (const mutate of [
    (d: typeof raw) => {
      d.hours[0].values.pop();
    },
    (d: typeof raw) => {
      d.hours[0].values[0][0] = -1;
    },
    (d: typeof raw) => {
      d.hours[0].values[0][1] = null;
    },
    (d: typeof raw) => {
      d.zones[1].id = d.zones[0].id;
    },
    (d: typeof raw) => {
      d.hours[1].time = d.hours[0].time;
    },
  ]) {
    const d = structuredClone(raw);
    mutate(d);
    assert.throws(() => parseDemo(d));
  }
});
test('empty filter is safe and colors clamp out-of-range values', () => {
  const d = parseDemo(raw);
  assert.deepEqual(summarize(d, 0, [], 'borough_context'), { actual: 0, forecast: 0, mae: 0 });
  assert.equal(color(0, 0), color(-5, 10));
  assert.equal(color(50, 10), color(10, 10));
});
test('ranks only the selected zones by absolute error and retains its direction', () => {
  const d = parseDemo(structuredClone(raw));
  d.hours[0]!.values[0] = [10, 4, 10, 0];
  d.hours[0]!.values[1] = [0, 8, 0, 0];
  d.hours[0]!.values[2] = [0, 100, 0, 0];
  assert.deepEqual(forecastMisses(d, 0, [0, 1], 'hist_gradient_boosting'), [
    { zoneIndex: 1, actual: 0, forecast: 8, error: 8 },
    { zoneIndex: 0, actual: 10, forecast: 4, error: -6 },
  ]);
  assert.equal(forecastMisses(d, 0, [0], 'borough_context')[0]!.error, 0);
  assert.deepEqual(forecastMisses(d, 0, [], 'previous_week_168h'), []);
});
test('miss ranking follows the chosen hour and breaks ties by zone ID', () => {
  const d = parseDemo(structuredClone(raw));
  const indices = [0, 1, 2, 3, 4, 5];
  indices.forEach((i) => {
    d.hours[1]!.values[i] = [10, 10, 10, 10];
  });
  d.hours[1]!.values[5] = [10, 15, 10, 10];
  const ranked = forecastMisses(d, 1, [...indices].reverse(), 'hist_gradient_boosting');
  assert.equal(ranked.length, 5);
  assert.equal(ranked[0]!.zoneIndex, 5);
  assert.deepEqual(
    ranked.slice(1).map((row) => d.zones[row.zoneIndex]!.id),
    indices
      .slice(0, 5)
      .map((i) => d.zones[i]!.id)
      .sort((a, b) => a - b)
      .slice(0, 4),
  );
});
