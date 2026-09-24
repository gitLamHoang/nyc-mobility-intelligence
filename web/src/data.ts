export const modelNames = {
  hist_gradient_boosting: 'Temporal model',
  borough_context: 'Borough context',
  previous_week_168h: 'Previous week',
} as const;
export type Model = keyof typeof modelNames;
export type Zone = { id: number; name: string; borough: string; path: string };
export type Demo = {
  schemaVersion: 1;
  studyId: string;
  scope: string;
  columns: string[];
  zones: Zone[];
  hours: { time: string; values: number[][] }[];
  viewBox: number[];
  provenance: Record<string, string>;
};
export function parseDemo(value: unknown): Demo {
  if (!value || typeof value !== 'object') throw new Error('Missing dataset');
  const d = value as Demo;
  if (
    d.schemaVersion !== 1 ||
    !Array.isArray(d.zones) ||
    !d.zones.length ||
    !Array.isArray(d.hours) ||
    !d.hours.length ||
    !Array.isArray(d.columns) ||
    d.columns.join(',') !== 'demand,hist_gradient_boosting,borough_context,previous_week_168h' ||
    !Array.isArray(d.viewBox) ||
    d.viewBox.length !== 4 ||
    !d.viewBox.every(Number.isFinite) ||
    d.viewBox[2]! <= 0 ||
    d.viewBox[3]! <= 0
  ) {
    throw new Error('Unsupported dataset shape');
  }
  const ids = new Set<number>();
  for (const zone of d.zones) {
    if (
      !Number.isInteger(zone.id) ||
      ids.has(zone.id) ||
      typeof zone.name !== 'string' ||
      typeof zone.borough !== 'string' ||
      typeof zone.path !== 'string' ||
      !/^[MLZ0-9.,\s-]+$/.test(zone.path)
    ) {
      throw new Error('Invalid or duplicate zone');
    }
    ids.add(zone.id);
  }
  let previous = -Infinity;
  for (const hour of d.hours) {
    const time = Date.parse(hour.time);
    if (
      !Number.isFinite(time) ||
      time <= previous ||
      !Array.isArray(hour.values) ||
      hour.values.length !== d.zones.length ||
      hour.values.some(
        (row) =>
          !Array.isArray(row) ||
          row.length !== d.columns.length ||
          row.some((v) => !Number.isFinite(v) || v < 0),
      )
    ) {
      throw new Error('Invalid hourly observations');
    }
    previous = time;
  }
  return d;
}
export function zoneIndices(d: Demo, borough: string): number[] {
  return d.zones.flatMap((z, i) =>
    borough === 'All boroughs' || z.borough === borough ? [i] : [],
  );
}
export function summarize(d: Demo, hour: number, indices: number[], model: Model) {
  const column = d.columns.indexOf(model);
  const rows = indices.map((i) => d.hours[hour]!.values[i]!);
  return {
    actual: rows.reduce((sum, row) => sum + row[0]!, 0),
    forecast: rows.reduce((sum, row) => sum + row[column]!, 0),
    mae: rows.length
      ? rows.reduce((sum, row) => sum + Math.abs(row[0]! - row[column]!), 0) / rows.length
      : 0,
  };
}
export function color(value: number, max: number): string {
  const t = max > 0 ? Math.sqrt(Math.max(0, Math.min(1, value / max))) : 0;
  const a = [225, 235, 219],
    b = [19, 103, 93];
  return `rgb(${a.map((v, i) => Math.round(v + (b[i]! - v) * t)).join(',')})`;
}
