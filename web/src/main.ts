import './style.css';
import {
  boroughComparisons,
  color,
  forecastMisses,
  modelNames,
  parseDemo,
  summarize,
  zoneIndices,
} from './data.ts';
import type { Model } from './data.ts';
import { readView, viewURL } from './view.ts';
const app = document.querySelector<HTMLDivElement>('#app')!;
const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const timeFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
});
const esc = (s: string) =>
  s.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!,
  );
async function start() {
  const response = await fetch(`${import.meta.env.BASE_URL}data/demo.json`);
  if (!response.ok) throw new Error('The study could not be loaded. Please reload.');
  const d = parseDemo(await response.json());
  let { hour, borough, model, metric, selected } = readView(new URL(location.href), d);
  app.innerHTML = `
    <a class="skip-link" href="#explorer">Skip to explorer</a><header><a class="brand" href="./"><span class="brand-mark">M<span>↗</span></span><span>NYC MOBILITY<br><b>INTELLIGENCE</b></span></a><nav><a href="https://github.com/gitLamHoang/nyc-mobility-intelligence">Code & methodology ↗</a><a href="https://github.com/gitLamHoang">Built by Lam Phan ↗</a></nav></header>
    <main><section class="intro"><div><p class="eyebrow"><span class="dot"></span> OPEN MOBILITY LAB · HISTORICAL EXPLORER</p><h1>A city in motion.<br><span>A forecast you can inspect.</span></h1><p class="lede">Where does taxi demand concentrate—and where do forecasts miss? Explore recorded pickups and model estimates across 262 New York City zones.</p></div><aside class="study-note"><span class="eyebrow">THE STUDY WINDOW</span><strong>07—08 APR <span>2026</span></strong><p>48 hours · 262 zones · official NYC TLC data</p><span class="pill">Historical validation · not a live forecast</span></aside></section>
    <section id="explorer" class="workspace" aria-label="Demand explorer" tabindex="-1"><div class="explorer-toolbar"><div><p class="eyebrow">01 / EXPLORE THE CITY</p><h2>Explore demand. Inspect the misses.</h2><p class="toolbar-help">Choose a borough and model, then select a zone on the map or in the table.</p></div><div class="controls"><label>Borough<select id="borough">${['All boroughs', ...new Set(d.zones.map((z) => z.borough))].map((b) => `<option>${esc(b)}</option>`).join('')}</select></label><label>Compare model<select id="model">${Object.entries(
      modelNames,
    )
      .map(([v, n]) => `<option value="${v}">${n}</option>`)
      .join(
        '',
      )}</select></label><div class="share-control"><button id="copy-view" type="button">Copy view link</button><a id="share-view" class="text-link">Open view link ↗</a><span id="share-status" role="status"></span></div></div></div>
    <div class="stats" aria-live="polite"><div><span>RECORDED PICKUPS</span><strong id="actual"></strong></div><div><span>MODEL ESTIMATE</span><strong id="forecast"></strong></div><div><span>AVG. ABSOLUTE ERROR / ZONE</span><strong id="mae"></strong></div><p>Selected hour & borough.<br>Counts describe historical pickups.</p></div>
    <section class="misses" aria-labelledby="boroughs-title"><h3 id="boroughs-title">Compare boroughs</h3><p>All boroughs at the selected hour, ranked by average absolute error per zone. Total absolute error adds zone misses without cancellation. Select a borough to filter the explorer.</p><button id="all-boroughs" type="button">Show all boroughs</button><div class="misses-scroll"><table><caption id="boroughs-scope"></caption><thead><tr><th scope="col">Borough</th><th scope="col">Recorded</th><th scope="col">Estimate</th><th scope="col">Total abs. error</th><th scope="col">Avg. / zone</th></tr></thead><tbody id="boroughs-rows"></tbody></table></div></section>
    <div class="explorer-grid"><div class="map-panel"><div class="map-top"><div class="segmented" aria-label="Map measure"><button data-metric="demand" aria-pressed="true">Pickups</button><button data-metric="error" aria-pressed="false">Forecast error</button></div><span class="map-hint">Select a zone to inspect →</span></div><svg id="map" viewBox="${d.viewBox.join(' ')}" role="img" aria-label="New York City taxi zone choropleth">${d.zones.map((z, i) => `<path data-zone="${i}" d="${z.path}" fill-rule="evenodd"><title>${esc(z.name)} · ${esc(z.borough)}</title></path>`).join('')}</svg><div class="legend"><span id="legend-label">Fewer pickups</span><span class="gradient"></span><span id="legend-max"></span></div><p class="map-caption">NYC TLC taxi zones · simplified display geometry · scale uses square-root color intensity</p></div>
    <aside class="detail-panel"><p class="eyebrow">02 / INSPECT A NEIGHBORHOOD</p><label class="zone-label">Select a zone<select id="zone"></select></label><p id="zone-borough" class="zone-borough"></p><h3 id="zone-name"></h3><div class="zone-stats"><div><span>Recorded</span><strong id="zone-actual"></strong></div><div><span>Estimate</span><strong id="zone-forecast"></strong></div><div><span>Abs. error</span><strong id="zone-error"></strong></div></div><h4>Its 48-hour rhythm</h4><p id="chart-help" class="chart-help">Select an hour on the chart, or focus it and use the arrow keys. Home and End jump to the first and last hour.</p><svg id="chart" viewBox="0 0 360 150" role="slider" tabindex="0" aria-label="Hour on the zone chart" aria-describedby="chart-help" aria-orientation="horizontal" aria-valuemin="0" aria-valuemax="47"></svg><div class="chart-legend"><span>● Recorded pickups</span><span>— Model estimate</span></div><p class="detail-note">A retrospective comparison: these models were evaluated on April data after training only on earlier months. Values are hourly counts, not individual journeys.</p><a class="text-link" href="https://github.com/gitLamHoang/nyc-mobility-intelligence/blob/main/docs/EXPLORER.md">How this demo was built ↗</a></aside></div>
    <div class="timeline"><div><span class="eyebrow">NEW YORK LOCAL TIME</span><strong id="time-label"></strong></div><button id="previous" aria-label="Previous hour">←</button><label class="slider-label" for="hour">Hour in study window</label><input id="hour" type="range" min="0" max="47" value="16" aria-label="Hour in study window"><button id="next" aria-label="Next hour">→</button><span class="timeline-end">48 HOURS</span></div>
    <section class="misses" aria-labelledby="misses-title"><h3 id="misses-title">Largest forecast misses</h3><p>Select a zone to inspect its trace. Under means the estimate fell below recorded pickups; over means it exceeded them.</p><div class="misses-scroll"><table><caption id="misses-scope"></caption><thead><tr><th scope="col">Zone</th><th scope="col">Recorded</th><th scope="col">Estimate</th><th scope="col">Forecast error</th></tr></thead><tbody id="misses-rows"></tbody></table></div></section></section>
    <section class="context"><div><p class="eyebrow">03 / WHAT THE EVIDENCE SAYS</p><h2>Better decisions start<br>with honest comparisons.</h2><p>The question: could demand forecasts help mobility teams plan where capacity is needed? This prototype makes the evidence inspectable. Operational value still needs validation with users.</p></div><article><span class="card-number">01</span><h3>A baseline is part of the product.</h3><p>Switch to “Previous week” to compare with a simple same-hour baseline. This two-day view illustrates behavior; it is not the full evaluation.</p></article><article><span class="card-number">02</span><h3>Small gains deserve scrutiny.</h3><p>Borough context reduced pooled February–April MAE by 0.416%, while worsening errors in sparse zones. It has not replaced the serving model.</p><a href="https://github.com/gitLamHoang/nyc-mobility-intelligence/blob/main/reports/borough/20260924T162406Z-c35816/metrics.json">Inspect the measured experiment ↗</a></article><article><span class="card-number">03</span><h3>Keep the final test honest.</h3><p>May 2026 remains sealed until the documented model freeze. Public demo data comes from April validation only. No customer deployment is claimed.</p></article></section>
    </main><footer><span>NYC Mobility Intelligence · Built by Lam Phan</span><a href="https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page">Official data source ↗</a><a href="https://github.com/gitLamHoang/nyc-mobility-intelligence">Reproduce the work ↗</a></footer>`;
  const el = (id: string) => document.getElementById(id)!;
  const text = (id: string, value: string) => {
    el(id).textContent = value;
  };
  function render() {
    text('share-status', '');
    const indices = zoneIndices(d, borough),
      active = new Set(indices),
      column = d.columns.indexOf(model);
    if (!active.has(selected)) selected = indices[0]!;
    const stats = summarize(d, hour, indices, model);
    text('actual', fmt.format(stats.actual));
    text('forecast', fmt.format(stats.forecast));
    text('mae', stats.mae.toFixed(2));
    const measures = d.hours[hour]!.values.map((v) =>
      metric === 'demand' ? v[0]! : Math.abs(v[0]! - v[column]!),
    );
    const max = Math.max(...indices.map((i) => measures[i]!));
    document.querySelectorAll<SVGPathElement>('#map path').forEach((path, i) => {
      path.style.fill = active.has(i) ? color(measures[i]!, max) : '#e8eae4';
      path.classList.toggle('selected', i === selected);
      path.classList.toggle('inactive', !active.has(i));
    });
    text('legend-label', metric === 'demand' ? '0 pickups' : '0 absolute error');
    text('legend-max', max.toFixed(0));
    const zoneSelect = el('zone') as HTMLSelectElement;
    zoneSelect.innerHTML = [...indices]
      .sort((a, b) => d.zones[a]!.name.localeCompare(d.zones[b]!.name))
      .map(
        (i) =>
          `<option value="${i}"${i === selected ? ' selected' : ''}>${esc(d.zones[i]!.name)}</option>`,
      )
      .join('');
    const z = d.zones[selected]!,
      values = d.hours[hour]!.values[selected]!;
    text('zone-name', z.name);
    text('zone-borough', `${z.borough} / Zone ${z.id}`);
    text('zone-actual', fmt.format(values[0]!));
    text('zone-forecast', values[column]!.toFixed(1));
    text('zone-error', Math.abs(values[0]! - values[column]!).toFixed(1));
    const peak = Math.max(
      1,
      ...d.hours.flatMap((h) => [h.values[selected]![0]!, h.values[selected]![column]!]),
    );
    const line = (col: number) =>
      d.hours
        .map(
          (h, i) =>
            `${12 + (i * 336) / (d.hours.length - 1)},${125 - (h.values[selected]![col]! / peak) * 110}`,
        )
        .join(' ');
    const x = 12 + (hour * 336) / (d.hours.length - 1);
    el('chart').innerHTML =
      `<line x1="12" y1="125" x2="348" y2="125" stroke="#d6dfd5"/><line x1="${x}" y1="10" x2="${x}" y2="125" stroke="#b2b9ae" stroke-dasharray="3 3"/><polyline points="${line(0)}" fill="none" stroke="#17675d" stroke-width="2.5"/><polyline points="${line(column)}" fill="none" stroke="#c07039" stroke-width="2" stroke-dasharray="5 3"/><circle cx="${x}" cy="${125 - (values[0]! / peak) * 110}" r="3.5" fill="#17675d"/><circle cx="${x}" cy="${125 - (values[column]! / peak) * 110}" r="3" fill="#c07039"/><text x="12" y="144">Apr 7, midnight</text><text x="255" y="144">Apr 8, 11 PM</text>`;
    const time = timeFmt.format(new Date(d.hours[hour]!.time));
    text('boroughs-scope', `${time} New York time · ${modelNames[model]} · Filter: ${borough}`);
    el('boroughs-rows').innerHTML = boroughComparisons(d, hour, model)
      .map(
        (row) =>
          `<tr><th scope="row"><button data-borough="${esc(row.borough)}" aria-pressed="${row.borough === borough}">${esc(row.borough)}<span>${row.zones} zones</span></button></th><td>${fmt.format(row.actual)}</td><td>${row.forecast.toFixed(1)}</td><td>${row.absoluteError.toFixed(1)}</td><td>${row.mae.toFixed(2)}</td></tr>`,
      )
      .join('');
    el('all-boroughs').setAttribute('aria-pressed', String(borough === 'All boroughs'));
    text('time-label', time);
    el('chart').setAttribute('aria-valuenow', String(hour));
    el('chart').setAttribute(
      'aria-valuetext',
      `${time} New York time; ${z.name}; recorded ${fmt.format(values[0]!)} pickups; estimate ${values[column]!.toFixed(1)}`,
    );
    text('misses-scope', `Top 5 · ${time} New York time · ${borough} · ${modelNames[model]}`);
    el('misses-rows').innerHTML = forecastMisses(d, hour, indices, model)
      .map(({ zoneIndex, actual, forecast, error }) => {
        const zone = d.zones[zoneIndex]!;
        const direction = error < 0 ? 'Under' : 'Over';
        const difference = error === 0 ? 'Exact' : `${direction} by ${Math.abs(error).toFixed(1)}`;
        return `<tr><th scope="row"><button data-miss-zone="${zoneIndex}" aria-pressed="${zoneIndex === selected}">${esc(zone.name)}<span>${esc(zone.borough)} · Zone ${zone.id}</span></button></th><td>${fmt.format(actual)}</td><td>${forecast.toFixed(1)}</td><td>${difference}</td></tr>`;
      })
      .join('');
    (el('borough') as HTMLSelectElement).value = borough;
    (el('model') as HTMLSelectElement).value = model;
    document
      .querySelectorAll<HTMLButtonElement>('[data-metric]')
      .forEach((button) =>
        button.setAttribute('aria-pressed', String(button.dataset.metric === metric)),
      );
    const url = viewURL(new URL(location.href), d, { hour, borough, model, metric, selected });
    (el('share-view') as HTMLAnchorElement).href = url.href;
    if (url.href !== location.href) history.replaceState(null, '', url);
    (el('hour') as HTMLInputElement).value = String(hour);
    el('hour').setAttribute('aria-valuetext', `${time} New York time`);
    (el('previous') as HTMLButtonElement).disabled = hour === 0;
    (el('next') as HTMLButtonElement).disabled = hour === d.hours.length - 1;
  }
  el('copy-view').addEventListener('click', async () => {
    const button = el('copy-view') as HTMLButtonElement;
    button.disabled = true;
    try {
      await navigator.clipboard.writeText((el('share-view') as HTMLAnchorElement).href);
      text('share-status', 'Link copied. Ready to share.');
    } catch {
      text('share-status', 'Copy the link from your address bar.');
    } finally {
      button.disabled = false;
    }
  });
  el('borough').addEventListener('change', (e) => {
    borough = (e.target as HTMLSelectElement).value;
    render();
  });
  el('boroughs-rows').addEventListener('click', (e) => {
    const button = (e.target as Element).closest<HTMLButtonElement>('button[data-borough]');
    if (!button) return;
    borough = button.dataset.borough!;
    render();
    // Restore focus after replacing the table rows, including when their order changes.
    Array.from(el('boroughs-rows').querySelectorAll<HTMLButtonElement>('button'))
      .find((row) => row.dataset.borough === borough)
      ?.focus({ preventScroll: true });
  });
  el('all-boroughs').addEventListener('click', () => {
    borough = 'All boroughs';
    render();
  });
  el('model').addEventListener('change', (e) => {
    model = (e.target as HTMLSelectElement).value as Model;
    render();
  });
  el('zone').addEventListener('change', (e) => {
    selected = Number((e.target as HTMLSelectElement).value);
    render();
  });
  el('misses-rows').addEventListener('click', (e) => {
    const button = (e.target as Element).closest<HTMLButtonElement>('button[data-miss-zone]');
    if (button) {
      selected = Number(button.dataset.missZone);
      render();
      el('zone').focus({ preventScroll: true });
      el('zone').scrollIntoView({
        block: 'nearest',
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
          ? 'instant'
          : 'smooth',
      });
    }
  });
  el('chart').addEventListener('click', (e) => {
    const chart = el('chart') as unknown as SVGSVGElement;
    const matrix = chart.getScreenCTM();
    if (!matrix) return;
    const point = new DOMPoint(e.clientX, e.clientY).matrixTransform(matrix.inverse());
    hour = Math.max(
      0,
      Math.min(d.hours.length - 1, Math.round(((point.x - 12) / 336) * (d.hours.length - 1))),
    );
    render();
    chart.focus({ preventScroll: true });
  });
  el('chart').addEventListener('keydown', (e) => {
    const targetHour = {
      ArrowLeft: hour - 1,
      ArrowDown: hour - 1,
      ArrowRight: hour + 1,
      ArrowUp: hour + 1,
      Home: 0,
      End: d.hours.length - 1,
    }[e.key];
    if (targetHour === undefined) return;
    e.preventDefault();
    hour = Math.max(0, Math.min(d.hours.length - 1, targetHour));
    render();
  });
  el('hour').addEventListener('input', (e) => {
    hour = Number((e.target as HTMLInputElement).value);
    render();
  });
  el('previous').addEventListener('click', () => {
    hour = Math.max(0, hour - 1);
    render();
  });
  el('next').addEventListener('click', () => {
    hour = Math.min(d.hours.length - 1, hour + 1);
    render();
  });
  el('map').addEventListener('click', (e) => {
    const path = (e.target as Element).closest<SVGPathElement>('path[data-zone]');
    if (path && !path.classList.contains('inactive')) {
      selected = Number(path.dataset.zone);
      render();
    }
  });
  document.querySelectorAll<HTMLButtonElement>('[data-metric]').forEach((button) =>
    button.addEventListener('click', () => {
      metric = button.dataset.metric as 'demand' | 'error';
      render();
    }),
  );
  window.addEventListener('popstate', () => {
    ({ hour, borough, model, metric, selected } = readView(new URL(location.href), d));
    render();
  });
  render();
}
start().catch((error) => {
  app.replaceChildren();
  const p = document.createElement('p');
  p.className = 'loading';
  p.role = 'alert';
  p.textContent = `Unable to display the study. ${error instanceof Error ? error.message : 'Please try again.'}`;
  app.append(p);
});
