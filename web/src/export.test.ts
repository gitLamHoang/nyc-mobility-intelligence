import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { modelNames, parseDemo, summarize, zoneIndices } from './data.ts';
import type { Model } from './data.ts';
import { exportHour } from './export.ts';

const d = parseDemo(
  JSON.parse(readFileSync(new URL('../public/data/demo.json', import.meta.url), 'utf8')),
);

test('CSV follows every hour, borough and model and reconciles with displayed statistics', () => {
  for (let hour = 0; hour < d.hours.length; hour++) {
    for (const borough of ['All boroughs', ...new Set(d.zones.map((z) => z.borough))]) {
      for (const model of Object.keys(modelNames) as Model[]) {
        const file = exportHour(d, hour, borough, model);
        const indices = zoneIndices(d, borough);
        const lines = file.csv.trimEnd().split('\r\n');
        assert.equal(file.count, indices.length);
        assert.equal(lines.length, indices.length + 1);
        assert.equal(
          lines[0],
          'study_id,scope,time_utc,zone_id,zone_name,borough,model,recorded_pickups,estimate,error_estimate_minus_recorded,absolute_error',
        );
        const totals = [0, 0, 0];
        lines.slice(1).forEach((line, row) => {
          const i = indices[row]!;
          const zone = d.zones[i]!;
          assert.ok(line.includes(`${new Date(d.hours[hour]!.time).toISOString()},${zone.id},`));
          assert.ok(line.includes(`,${model},`));
          const values = line.split(',').slice(-4).map(Number);
          const actual = d.hours[hour]!.values[i]![0]!;
          const forecast = d.hours[hour]!.values[i]![d.columns.indexOf(model)]!;
          assert.deepEqual(values, [
            actual,
            forecast,
            forecast - actual,
            Math.abs(forecast - actual),
          ]);
          totals[0]! += values[0]!;
          totals[1]! += values[1]!;
          totals[2]! += values[3]!;
        });
        const stats = summarize(d, hour, indices, model);
        assert.equal(totals[0], stats.actual);
        assert.equal(totals[1], stats.forecast);
        assert.equal(totals[2]! / indices.length, stats.mae);
        assert.match(file.filename, /Z-.*\.csv$/);
      }
    }
  }
});

test('CSV quotes commas, double quotes and line breaks without rounding values', () => {
  const fixture = structuredClone(d);
  fixture.studyId = 'study';
  fixture.scope = 'historical validation';
  fixture.zones = [{ ...d.zones[0]!, id: 99, name: 'A, "B"\nC', borough: 'Queens' }];
  fixture.hours = [{ time: '2026-04-08T23:00:00-04:00', values: [[2, 1.125, 3.25, 2]] }];
  const file = exportHour(fixture, 0, 'Queens', 'hist_gradient_boosting');
  assert.ok(
    file.csv.endsWith(
      'study,historical validation,2026-04-09T03:00:00.000Z,99,"A, ""B""\nC",Queens,hist_gradient_boosting,2,1.125,-0.875,0.875\r\n',
    ),
  );
  assert.equal(file.filename, 'nyc-mobility-2026040903Z-queens-hist_gradient_boosting.csv');
});
