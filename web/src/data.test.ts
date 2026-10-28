import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  boroughComparisons,
  modelNames,
  parseDemo,
  zoneIndices,
  summarize,
  forecastMisses,
  color,
  zoneModelErrors,
  zoneDailySummaries,
  zoneLargestMissHour,
} from './data.ts';
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
test('borough comparison ranks per-zone errors without cancelling opposing misses', () => {
  const d = parseDemo(structuredClone(raw));
  d.zones = d.zones.slice(0, 3).map((z, i) => ({ ...z, borough: i < 2 ? 'Brooklyn' : 'Queens' }));
  d.hours = [
    {
      time: d.hours[0]!.time,
      values: [
        [10, 5, 10, 0],
        [0, 5, 0, 0],
        [20, 14, 20, 0],
      ],
    },
    {
      time: d.hours[1]!.time,
      values: [
        [0, 8, 0, 0],
        [0, 8, 0, 0],
        [0, 0, 0, 0],
      ],
    },
  ];
  assert.deepEqual(boroughComparisons(d, 0, 'hist_gradient_boosting'), [
    { borough: 'Queens', zones: 1, actual: 20, forecast: 14, mae: 6, absoluteError: 6 },
    { borough: 'Brooklyn', zones: 2, actual: 10, forecast: 10, mae: 5, absoluteError: 10 },
  ]);
  assert.equal(boroughComparisons(d, 1, 'hist_gradient_boosting')[0]!.borough, 'Brooklyn');
  const exact = boroughComparisons(d, 0, 'borough_context');
  assert.deepEqual(
    exact.map((r) => [r.borough, r.mae]),
    [
      ['Brooklyn', 0],
      ['Queens', 0],
    ],
  );
});
test('borough totals reconcile with every published hour and model', () => {
  const d = parseDemo(raw);
  for (let hour = 0; hour < d.hours.length; hour++) {
    for (const model of Object.keys(modelNames) as (keyof typeof modelNames)[]) {
      const rows = boroughComparisons(d, hour, model);
      const all = summarize(d, hour, zoneIndices(d, 'All boroughs'), model);
      assert.equal(
        rows.reduce((n, r) => n + r.zones, 0),
        262,
      );
      assert.equal(
        rows.reduce((n, r) => n + r.actual, 0),
        all.actual,
      );
      assert.ok(Math.abs(rows.reduce((n, r) => n + r.forecast, 0) - all.forecast) < 1e-7);
      assert.ok(Math.abs(rows.reduce((n, r) => n + r.absoluteError, 0) / 262 - all.mae) < 1e-10);
    }
  }
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

test('zone MAE averages absolute hourly errors including zero demand without cancellation', () => {
  const d = parseDemo(structuredClone(raw));
  d.hours = d.hours.slice(0, 2);
  d.hours[0]!.values[0] = [10, 5, 10, 0];
  d.hours[1]!.values[0] = [0, 5, 0, 0];
  d.hours[0]!.values[1] = [1000, 0, 0, 0];
  assert.deepEqual(zoneModelErrors(d, 0), [
    { model: 'hist_gradient_boosting', mae: 5, meanError: 0 },
    { model: 'borough_context', mae: 0, meanError: 0 },
    { model: 'previous_week_168h', mae: 5, meanError: -5 },
  ]);
  assert.equal(
    zoneModelErrors(d, 1)[0]!.mae,
    (1000 + Math.abs(d.hours[1]!.values[1]![1]! - d.hours[1]!.values[1]![0]!)) / 2,
  );
});

test('zone average error retains overestimation and reconciles every model and zone', () => {
  const d = parseDemo(structuredClone(raw));
  d.hours = d.hours.slice(0, 2);
  d.hours[0]!.values[0] = [0, 8, 0, 0];
  d.hours[1]!.values[0] = [4, 6, 4, 4];
  assert.deepEqual(zoneModelErrors(d, 0)[0], {
    model: 'hist_gradient_boosting',
    mae: 5,
    meanError: 5,
  });
  const published = parseDemo(raw);
  for (let zone = 0; zone < published.zones.length; zone++) {
    for (const row of zoneModelErrors(published, zone)) {
      const column = published.columns.indexOf(row.model);
      const estimates = published.hours.reduce((sum, h) => sum + h.values[zone]![column]!, 0);
      const recorded = published.hours.reduce((sum, h) => sum + h.values[zone]![0]!, 0);
      assert.ok(Math.abs(row.meanError - (estimates - recorded) / published.hours.length) < 1e-10);
      assert.ok(Math.abs(row.meanError) <= row.mae + 1e-10);
    }
  }
});

test('daily summaries group by New York date and average hourly absolute errors', () => {
  const d = parseDemo(structuredClone(raw));
  d.hours = [
    {
      time: '2026-04-08T02:00:00Z',
      values: [
        [10, 5, 10, 0],
        [999, 0, 0, 0],
      ],
    },
    {
      time: '2026-04-08T03:00:00Z',
      values: [
        [0, 5, 0, 0],
        [999, 0, 0, 0],
      ],
    },
    {
      time: '2026-04-08T04:00:00Z',
      values: [
        [4, 10, 4, 0],
        [999, 0, 0, 0],
      ],
    },
  ];
  assert.deepEqual(zoneDailySummaries(d, 0, 'hist_gradient_boosting'), [
    { day: 'Apr 7, 2026', hours: 2, actual: 10, forecast: 10, mae: 5 },
    { day: 'Apr 8, 2026', hours: 1, actual: 4, forecast: 10, mae: 6 },
  ]);
  assert.deepEqual(
    zoneDailySummaries(d, 0, 'borough_context').map((r) => r.mae),
    [0, 0],
  );
});

test('daily totals and MAE reconcile every published zone and model with source hours', () => {
  const d = parseDemo(raw);
  for (let zone = 0; zone < d.zones.length; zone++) {
    for (const model of Object.keys(modelNames) as (keyof typeof modelNames)[]) {
      const days = zoneDailySummaries(d, zone, model);
      assert.deepEqual(
        days.map((r) => [r.day, r.hours]),
        [
          ['Apr 7, 2026', 24],
          ['Apr 8, 2026', 24],
        ],
      );
      days.forEach((day, i) => {
        const rows = d.hours.slice(i * 24, (i + 1) * 24).map((h) => h.values[zone]!);
        const column = d.columns.indexOf(model);
        assert.equal(
          day.actual,
          rows.reduce((n, row) => n + row[0]!, 0),
        );
        assert.equal(
          day.forecast,
          rows.reduce((n, row) => n + row[column]!, 0),
        );
        assert.equal(
          day.mae,
          rows.reduce((n, row) => n + Math.abs(row[column]! - row[0]!), 0) / 24,
        );
      });
    }
  }
});

test('largest zone miss uses absolute error, model and earliest-hour ties including zero pickups', () => {
  const d = parseDemo(structuredClone(raw));
  d.hours = d.hours.slice(0, 3);
  d.hours[0]!.values[0] = [10, 10, 0, 10];
  d.hours[1]!.values[0] = [0, 8, 0, 0];
  d.hours[2]!.values[0] = [8, 0, 8, 8];
  d.hours[0]!.values[1] = [0, 0, 0, 0];
  d.hours[1]!.values[1] = [0, 0, 0, 0];
  d.hours[2]!.values[1] = [0, 20, 0, 0];
  assert.equal(zoneLargestMissHour(d, 0, 'hist_gradient_boosting'), 1);
  assert.equal(zoneLargestMissHour(d, 0, 'borough_context'), 0);
  assert.equal(zoneLargestMissHour(d, 0, 'previous_week_168h'), 0);
  assert.equal(zoneLargestMissHour(d, 1, 'hist_gradient_boosting'), 2);
});

test('largest miss hour matches an independent ranking for every published zone and model', () => {
  const d = parseDemo(raw);
  for (let zone = 0; zone < d.zones.length; zone++) {
    for (const model of Object.keys(modelNames) as (keyof typeof modelNames)[]) {
      const column = d.columns.indexOf(model);
      const ranked = d.hours
        .map((h, i) => ({
          hour: i,
          error: Math.abs(h.values[zone]![column]! - h.values[zone]![0]!),
        }))
        .sort((a, b) => b.error - a.error || a.hour - b.hour);
      assert.equal(zoneLargestMissHour(d, zone, model), ranked[0]!.hour);
    }
  }
});
