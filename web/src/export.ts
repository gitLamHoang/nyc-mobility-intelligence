import { zoneIndices } from './data.ts';
import type { Demo, Model } from './data.ts';

export function exportHour(d: Demo, hour: number, borough: string, model: Model) {
  const snapshot = d.hours[hour]!;
  const indices = zoneIndices(d, borough);
  const column = d.columns.indexOf(model);
  const rows = [
    [
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
    ],
    ...indices.map((i) => {
      const zone = d.zones[i]!;
      const actual = snapshot.values[i]![0]!;
      const forecast = snapshot.values[i]![column]!;
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
    }),
  ];
  const csv =
    rows
      .map((row) =>
        row
          .map((cell) => {
            const value = String(cell);
            return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
          })
          .join(','),
      )
      .join('\r\n') + '\r\n';
  const stamp = new Date(snapshot.time).toISOString().slice(0, 13).replaceAll(/[-:T]/g, '');
  return {
    csv,
    count: indices.length,
    filename: `nyc-mobility-${stamp}Z-${borough.toLowerCase().replaceAll(' ', '-')}-${model}.csv`,
  };
}
