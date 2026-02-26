# Interactive Docs Toolkit

Standalone toolkit to generate interactive, hotspot-driven walkthrough docs from a live dashboard.

## Repository

- Local path: `/Users/amank/Code/interactive-docs-toolkit`
- Outputs: `runs/<RUN_TS>/...`

## What It Produces

Per run:
- `manifests/component_manifest.json`
- `manifests/hotspot_manifest.json`
- `manifests/story_content.json`
- `interactive-site-src/` (generated Next.js source)
- `interactive-site-static/` (static export)
- `docs/INTERACTIVE_WALKTHROUGH_OPEN.html`
- `manifests/qa_report_interactive.json`

## Prerequisites

1. Node.js + npm
2. Python runtime with required libs (`pillow` needed by business semantics builder)
3. Reachable dashboard URL
4. Reachable API health URL

## Onboarding: Wiring To Your Project

Wire these runtime inputs when you run the toolkit:

```bash
DASHBOARD_URL=http://127.0.0.1:3000 \
API_HEALTH_URL=http://127.0.0.1:8000/api/health \
PYTHON_BIN=python3 \
CAPTURE_SPEC_PATH=/absolute/path/to/capture_spec.json \
./scripts/run_interactive_walkthrough.sh
```

What each input controls:
- `DASHBOARD_URL`: app to capture.
- `API_HEALTH_URL`: readiness check before capture.
- `PYTHON_BIN`: python used for `build_interactive_walkthrough.py` and semantics generation.
- `CAPTURE_SPEC_PATH`: state/action/component map for your UI.

Optional context vars used in manifests and deep links:
- `COUNTRY`, `PRODUCT`, `YEAR`, `VERSION`, `DATA_SOURCE`

## Capture Spec Wiring (Tool/Topic Agnostic)

Use `spec/capture_spec.example.json` as your starter template.

Key sections to wire:
- `navigation.tab_button_selector`: selector for tab click attempts.
- `navigation.fallback_url_template`: fallback URL if click navigation fails.
- `actions`: reusable typed action sequences.
- `states`: ordered capture states and component targets.
- `tab_meta`: business/source metadata mapped into the output manifests.

Supported action types:
- `click_text`
- `click_selector`
- `goto_tab`
- `goto_url`
- `set_theme`
- `wait_text`
- `wait_ms`
- `scroll_text`
- `press_key`

Component targeting priority:
1. `bbox`
2. `selectors` / `selector`
3. `anchors`

## Quick Start

```bash
cd /Users/amank/Code/interactive-docs-toolkit
npm install
./scripts/run_interactive_walkthrough.sh
```

Or:

```bash
npm run walkthrough:run
```

## Useful Overrides

```bash
RUN_TS=20260226_130000 \
PRUNE_SCREENSHOTS_AFTER_EXPORT=1 \
./scripts/run_interactive_walkthrough.sh
```

## Space Cleanup

Delete screenshot-heavy artifacts across runs:

```bash
./scripts/prune_screenshot_artifacts.sh
```

Delete screenshot-heavy artifacts for one run:

```bash
./scripts/prune_screenshot_artifacts.sh /Users/amank/Code/interactive-docs-toolkit/runs/<RUN_TS>
```
