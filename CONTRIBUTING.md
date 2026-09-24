# Contributing

Start with the [browser demo](docs/EXPLORER.md) for a small, self-contained path. For research, read the [current state](PROJECT_STATE.md) and the protocol for the stage you want to change.

```bash
uv sync --frozen --python 3.12
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd web
npm ci
npm test
npm run build
```

Please include the problem, a reproducible example and evidence for your change. Synthetic fixtures are appropriate for tests; published project results must use official/reputable real data. Keep large tables, raw observations, credentials and model binaries out of commits. Never evaluate May 2026 or tune against it before the documented final freeze. Preserve immutable experiment evidence and record failed hypotheses alongside improvements.

For frontend changes, verify the actual interface at desktop and mobile widths, including keyboard controls, empty/error states and the relevant data filters. The compact demo is historical evidence; keep its scope and source hashes visible.
