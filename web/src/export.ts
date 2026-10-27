import { zoneIndices } from './data.ts';
import type { Demo, Model } from './data.ts';

const columns = [
  'study_id',
  'scope',
  'time_utc',
  'zone_id',
  'zone_name',
  'borough',
  'model',
  'recorded_pickups',
  'estimate',
  'error_estimate_minus_recorded',
  'absolute_error',
];

function exportRow(d: Demo, hour: number, zoneIndex: number, model: Model) {
  const snapshot = d.hours[hour]!;
  const zone = d.zones[zoneIndex]!;
  const actual = snapshot.values[zoneIndex]![0]!;
  const forecast = snapshot.values[zoneIndex]![d.columns.indexOf(model)]!;
  const error = forecast - actual;
  return [
    d.studyId,
    d.scope,
    new Date(snapshot.time).toISOString(),
    zone.id,
    zone.name,
    zone.borough,
    model,
    actual,
    forecast,
    error,
    Math.abs(error),
  ];
}

function serialize(rows: (string | number)[][]) {
  return (
    [columns, ...rows]
      .map((row) =>
        row
          .map((cell) => {
            const value = String(cell);
            return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
          })
          .join(','),
      )
      .join('\r\n') + '\r\n'
  );
}

function stamp(time: string) {
  return new Date(time).toISOString().slice(0, 13).replaceAll(/[-:T]/g, '');
}

export function exportHour(d: Demo, hour: number, borough: string, model: Model) {
  const indices = zoneIndices(d, borough);
  return {
    csv: serialize(indices.map((i) => exportRow(d, hour, i, model))),
    count: indices.length,
    filename: `nyc-mobility-${stamp(d.hours[hour]!.time)}Z-${borough.toLowerCase().replaceAll(' ', '-')}-${model}.csv`,
  };
}

export function exportZone(d: Demo, zoneIndex: number, model: Model) {
  return {
    csv: serialize(d.hours.map((_, hour) => exportRow(d, hour, zoneIndex, model))),
    count: d.hours.length,
    filename: `nyc-mobility-zone-${d.zones[zoneIndex]!.id}-${stamp(d.hours[0]!.time)}Z-${stamp(d.hours.at(-1)!.time)}Z-${model}.csv`,
  };
}
