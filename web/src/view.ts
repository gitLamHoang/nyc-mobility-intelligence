import { modelNames, zoneIndices } from './data.ts';
import type { Demo, Model } from './data.ts';
export type View = {
  hour: number;
  borough: string;
  model: Model;
  metric: 'demand' | 'error';
  selected: number;
};
export function readView(url: URL, d: Demo): View {
  const p = url.searchParams;
  const borough = d.zones.some((z) => z.borough === p.get('borough'))
    ? p.get('borough')!
    : 'All boroughs';
  const indices = zoneIndices(d, borough);
  const requestedHour = p.get('hour');
  const hour =
    requestedHour !== null && /^\d+$/.test(requestedHour) && Number(requestedHour) < d.hours.length
      ? Number(requestedHour)
      : Math.min(16, d.hours.length - 1);
  const model = p.get('model');
  const requestedZone = p.get('zone');
  const selected =
    requestedZone !== null && /^\d+$/.test(requestedZone)
      ? indices.find((i) => d.zones[i]!.id === Number(requestedZone))
      : indices.find((i) => d.zones[i]!.name === 'Midtown Center');
  return {
    hour,
    borough,
    model:
      model !== null && Object.hasOwn(modelNames, model)
        ? (model as Model)
        : 'hist_gradient_boosting',
    metric: p.get('metric') === 'error' ? 'error' : 'demand',
    selected: selected ?? indices[0]!,
  };
}
export function viewURL(url: URL, d: Demo, view: View): URL {
  const next = new URL(url);
  const values = {
    hour: String(view.hour),
    borough: view.borough,
    model: view.model,
    metric: view.metric,
    zone: String(d.zones[view.selected]!.id),
  };
  for (const [key, value] of Object.entries(values)) next.searchParams.set(key, value);
  return next;
}
