#!/usr/bin/env python3
"""Prepare and finalize interactive dashboard walkthrough artifacts under temp/ only."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_business_module() -> Any:
    script_path = Path(__file__).with_name("build_business_dashboard_docs.py")
    spec = importlib.util.spec_from_file_location("business_docs", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load business docs module: {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stage", choices=["prepare", "finalize"], required=True)
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to component manifest (default: <run-dir>/manifests/component_manifest.json)",
    )
    return parser.parse_args()


def canonical_dashboard_url(ctx: dict[str, Any], tab: str) -> str:
    return (
        "http://127.0.0.1:3000/?"
        f"tab={tab}&country={ctx['country']}&product={ctx['product']}"
        f"&year={ctx['year']}&version={ctx['version']}"
    )


def prepare_stage(run_dir: Path, manifest_path: Path) -> dict[str, Any]:
    bbd = load_business_module()
    component_manifest = read_json(manifest_path)

    captures: list[dict[str, Any]] = component_manifest.get("captures", [])
    states: list[dict[str, Any]] = component_manifest.get("states", [])
    if not captures or not states:
        raise SystemExit("Component manifest must contain `captures` and `states`.")

    ctx = component_manifest["canonical_context"]
    semantics_by_component = bbd.build_semantics(captures)

    section_template = bbd.SECTION_TEMPLATE
    callout_overrides = bbd.CALL_OUT_OVERRIDES

    state_map = {s["state_id"]: s for s in states}
    order_in_state: dict[str, int] = defaultdict(int)

    output_dir = run_dir / "interactive-site-static"
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # Copy unique screenshots into output dir and build public path map.
    screenshot_public_map: dict[str, str] = {}
    for state in states:
        src = Path(state["screenshot"])
        if not src.exists():
            raise SystemExit(f"Missing screenshot from state manifest: {src}")
        dst = screenshots_dir / src.name
        shutil.copy2(src, dst)
        screenshot_public_map[state["screenshot"]] = f"screenshots/{src.name}"

    hotspots: list[dict[str, Any]] = []
    story_rows: list[dict[str, Any]] = []

    for cap in captures:
        component_id = cap["component_id"]
        section = cap["section"]
        state_id = cap["state_id"]
        st = state_map[state_id]
        sem = semantics_by_component[component_id]

        template = section_template.get(section, section_template["tab-overview"])
        override = callout_overrides.get(component_id, {})

        tooltip_summary = {
            "title": override.get("title", template["title"]),
            "business_question": override.get("business_question", template["business_question"]),
            "kpi_name": override.get("kpi_name", template["kpi_name"]),
            "one_line_value": sem["recommended_next_action"],
        }

        order_in_state[state_id] += 1
        order = order_in_state[state_id]

        hotspot = {
            "hotspot_id": cap["hotspot_id"],
            "component_id": component_id,
            "tab": cap["tab"],
            "state": cap["state"],
            "state_id": state_id,
            "section": section,
            "screenshot": cap["screenshot"],
            "screenshot_public": screenshot_public_map[cap["screenshot"]],
            "bbox": cap["bbox"],
            "bbox_pct": cap["bbox_pct"],
            "z_index": 20 + order,
            "order_in_state": order,
            "tooltip_summary": tooltip_summary,
            "panel_ref": component_id,
            "panel_payload": {
                "component_id": component_id,
                "tab": cap["tab"],
                "state": cap["state"],
            },
            "live_dashboard_url": canonical_dashboard_url(ctx, cap["tab"]),
        }
        hotspots.append(hotspot)

        story_row = {
            "component_id": component_id,
            "hotspot_id": cap["hotspot_id"],
            "tab": cap["tab"],
            "state": cap["state"],
            "state_id": state_id,
            "section": section,
            "title": tooltip_summary["title"],
            "business_question": tooltip_summary["business_question"],
            "kpi_name": tooltip_summary["kpi_name"],
            "tab_business_purpose": sem["tab_business_purpose"],
            "why_this_exists": sem["why_this_exists"],
            "kpi_or_chart_definition": sem["kpi_or_chart_definition"],
            "formula": sem["formula"],
            "inputs": sem["inputs"],
            "unit_and_scale": sem["unit_and_scale"],
            "how_to_read_good_vs_risk": sem["how_to_read_good_vs_risk"],
            "decision_supported": sem["decision_supported"],
            "recommended_next_action": sem["recommended_next_action"],
            "misinterpretation_risks": sem["misinterpretation_risks"],
            "data_freshness_or_caveats": sem["data_freshness_or_caveats"],
            "worked_example": sem["worked_example"],
        }
        story_rows.append(story_row)

    tabs = []
    for st in states:
        if st["tab"] not in tabs:
            tabs.append(st["tab"])

    # Build paired views: merge light/dark states per tab into unified views.
    # Each view has screenshot_light and screenshot_dark, hotspots are shared.
    light_states = [s for s in states if "light" in s["state"]]
    dark_states = [s for s in states if "dark" in s["state"]]

    # Build dark lookup: tab -> list of dark states
    dark_by_tab: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ds in dark_states:
        dark_by_tab[ds["tab"]].append(ds)

    views: list[dict[str, Any]] = []
    for ls in light_states:
        tab = ls["tab"]
        # Try to find a matching dark state (same sub-variant or fallback to primary)
        light_variant = ls["state"].replace("light-", "").replace("light", "")
        dark_match = None
        for ds in dark_by_tab.get(tab, []):
            dark_variant = ds["state"].replace("dark-", "").replace("dark", "")
            if dark_variant == light_variant:
                dark_match = ds
                break
        # If no exact variant match, check for a generic (no-variant) dark state.
        # Only assign it to the FIRST light variant for this tab (the default sub-view).
        # Non-default sub-views get no dark_match → fall back to light screenshot (line 206).
        if dark_match is None and dark_by_tab.get(tab):
            first_light_for_tab = next((s for s in light_states if s["tab"] == tab), None)
            if first_light_for_tab and first_light_for_tab["state_id"] == ls["state_id"]:
                for ds in dark_by_tab[tab]:
                    dark_variant = ds["state"].replace("dark-", "").replace("dark", "")
                    if dark_variant == "":
                        dark_match = ds
                        break

        view_id = ls["state_id"].replace("-light", "").replace("light-", "").replace("light", ls["tab"])
        if view_id == ls["tab"]:
            view_id = ls["tab"]

        view = {
            "view_id": ls["state_id"],  # keep original as key for hotspot lookup
            "tab": tab,
            "variant": light_variant or "default",
            "nav_label": ls["nav_label"],
            "screenshot_light": screenshot_public_map[ls["screenshot"]],
            "screenshot_dark": screenshot_public_map[dark_match["screenshot"]] if dark_match else screenshot_public_map[ls["screenshot"]],
            "full_width": ls["full_width"],
            "full_height": ls["full_height"],
            "hotspot_ids": ls["hotspot_ids"],
        }
        views.append(view)

    hotspot_manifest = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "canonical_context": ctx,
        "tabs": tabs,
        "views": views,
        "states": [
            {
                "state_id": st["state_id"],
                "tab": st["tab"],
                "state": st["state"],
                "nav_label": st["nav_label"],
                "screenshot_public": screenshot_public_map[st["screenshot"]],
                "full_width": st["full_width"],
                "full_height": st["full_height"],
                "hotspot_ids": st["hotspot_ids"],
            }
            for st in states
        ],
        "hotspots": hotspots,
    }

    story_content = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "canonical_context": ctx,
        "rows": story_rows,
    }

    hotspot_manifest_path = run_dir / "manifests" / "hotspot_manifest.json"
    story_content_path = run_dir / "manifests" / "story_content.json"

    write_json(hotspot_manifest_path, hotspot_manifest)
    write_json(story_content_path, story_content)

    # Write the single-page app directly to output dir.
    write_single_page_app(output_dir, hotspot_manifest, story_content)

    return {
        "run_dir": str(run_dir),
        "hotspot_manifest": str(hotspot_manifest_path),
        "story_content": str(story_content_path),
        "output_dir": str(output_dir),
        "hotspot_count": len(hotspots),
        "view_count": len(views),
        "tab_count": len(tabs),
    }


def write_single_page_app(
    output_dir: Path,
    hotspot_manifest: dict[str, Any],
    story_content: dict[str, Any],
) -> None:
    """Write a self-contained single-page React walkthrough app."""
    manifest_json = json.dumps(hotspot_manifest)
    story_json = json.dumps(story_content)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>MMM Decision Walkthrough</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {{
  darkMode: 'class',
  theme: {{
    extend: {{
      colors: {{
        accent: {{ DEFAULT: '#6366f1', light: '#818cf8', dim: '#4f46e5' }},
        surface: {{ dark: '#0a0a0b', light: '#fafafa' }},
        card: {{ dark: 'rgba(17,17,20,0.95)', light: 'rgba(255,255,255,0.95)' }},
      }}
    }}
  }}
}}
</script>
<script crossorigin src="https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js"></script>
<script crossorigin src="https://cdn.jsdelivr.net/npm/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@babel/standalone@7.26.10/babel.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body, #root {{ height: 100vh; overflow: hidden; font-family: 'Inter', system-ui, sans-serif; }}
body {{ background: #0a0a0b; color: #fff; transition: background 300ms, color 300ms; }}
body.light {{ background: #fafafa; color: #0a0a0b; }}

.pill {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); backdrop-filter: blur(12px); }}
body.light .pill {{ background: rgba(0,0,0,0.04); border-color: rgba(0,0,0,0.08); }}

.drawer {{ background: rgba(17,17,20,0.95); border-left: 1px solid rgba(255,255,255,0.08); backdrop-filter: blur(20px); }}
body.light .drawer {{ background: rgba(255,255,255,0.95); border-left-color: rgba(0,0,0,0.08); }}

.hotspot-ring {{ border: 2px solid rgba(99,102,241,0.6); background: rgba(99,102,241,0.08); transition: all 150ms ease; }}
.hotspot-ring:hover, .hotspot-ring.active {{ border-color: #6366f1; background: rgba(99,102,241,0.18); box-shadow: 0 0 0 3px rgba(99,102,241,0.25); }}
.hotspot-badge {{ position: absolute; top: -10px; left: -10px; min-width: 22px; height: 22px; border-radius: 999px; background: #6366f1; color: #fff; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; border: 2px solid #0a0a0b; }}
body.light .hotspot-badge {{ border-color: #fafafa; }}

@keyframes pulse-ring {{ 0% {{ opacity: 0.4; transform: scale(1); }} 100% {{ opacity: 0; transform: scale(1.08); }} }}
.pulse {{ position: absolute; inset: -4px; border-radius: inherit; border: 2px solid rgba(99,102,241,0.5); animation: pulse-ring 1.2s ease-out infinite; pointer-events: none; }}

.section-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: #6366f1; font-weight: 600; margin-bottom: 4px; }}
body.light .section-label {{ color: #4f46e5; }}

.text-secondary {{ color: #94a3b8; }}
body.light .text-secondary {{ color: #64748b; }}

.border-subtle {{ border-color: rgba(255,255,255,0.08); }}
body.light .border-subtle {{ border-color: rgba(0,0,0,0.08); }}

.formula-block {{ font-family: ui-monospace, SFMono-Regular, monospace; font-size: 12px; background: rgba(99,102,241,0.08); border: 1px solid rgba(99,102,241,0.15); border-radius: 6px; padding: 8px; }}

.screenshot-stage {{ position: relative; overflow-y: auto; overflow-x: hidden; }}
.screenshot-stage img {{ width: 100%; display: block; }}

.drawer-enter {{ transform: translateX(100%); }}
.drawer-visible {{ transform: translateX(0); transition: transform 300ms cubic-bezier(0.32,0.72,0,1); }}
.drawer-exit {{ transform: translateX(100%); transition: transform 200ms ease-in; }}

.tooltip {{ position: absolute; z-index: 50; max-width: 280px; background: rgba(8,24,34,0.95); color: #f5fafb; border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; padding: 10px 12px; font-size: 12px; line-height: 1.45; box-shadow: 0 14px 36px rgba(0,0,0,0.35); pointer-events: none; }}
body.light .tooltip {{ background: rgba(255,255,255,0.97); color: #0a0a0b; border-color: rgba(0,0,0,0.1); box-shadow: 0 14px 36px rgba(0,0,0,0.12); }}
</style>
</head>
<body>
<div id="root"></div>

<script>
window.__HOTSPOT_MANIFEST__ = {manifest_json};
window.__STORY_CONTENT__ = {story_json};
</script>

<script type="text/babel" data-type="module">
const {{ useState, useMemo, useEffect, useRef, useCallback }} = React;

const TAB_TITLE = {{
  home: 'Home',
  'sales-impact': 'Sales Impact',
  'response-curves': 'Response Curves',
  'budget-allocator': 'Budget Allocator',
  experiment: 'Simulator',
  insights: 'Insights',
  settings: 'Settings',
  geography: 'Geography',
}};

function App() {{
  const manifest = window.__HOTSPOT_MANIFEST__;
  const storyContent = window.__STORY_CONTENT__;
  const tabs = manifest.tabs;
  const views = manifest.views;
  const allHotspots = manifest.hotspots;
  const storyMap = useMemo(() => {{
    const m = {{}};
    for (const row of storyContent.rows) m[row.component_id] = row;
    return m;
  }}, []);

  const [tabIndex, setTabIndex] = useState(0);
  const [isDark, setIsDark] = useState(true);
  const [activeHotspotId, setActiveHotspotId] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [hoveredHotspot, setHoveredHotspot] = useState(null);
  const [mode, setMode] = useState('guided');
  const tooltipRef = useRef(null);
  const containerRef = useRef(null);

  const currentTab = tabs[tabIndex];

  // Get views for current tab
  const tabViews = useMemo(() => views.filter(v => v.tab === currentTab), [currentTab, views]);
  const [viewIndex, setViewIndex] = useState(0);
  const currentView = tabViews[viewIndex] || tabViews[0];

  // Reset view index when tab changes
  useEffect(() => {{
    setViewIndex(0);
    setActiveHotspotId(null);
    setDrawerOpen(false);
    setHoveredHotspot(null);
  }}, [tabIndex]);

  // Get hotspots for current view
  const viewHotspots = useMemo(() => {{
    if (!currentView) return [];
    const ids = new Set(currentView.hotspot_ids);
    return allHotspots
      .filter(h => ids.has(h.hotspot_id))
      .sort((a, b) => a.order_in_state - b.order_in_state);
  }}, [currentView, allHotspots]);

  const activeStory = useMemo(() => {{
    if (!activeHotspotId) return null;
    const hs = viewHotspots.find(h => h.hotspot_id === activeHotspotId);
    return hs ? storyMap[hs.component_id] : null;
  }}, [activeHotspotId, viewHotspots, storyMap]);

  const activeHotspot = viewHotspots.find(h => h.hotspot_id === activeHotspotId);

  // Screenshot path based on theme
  const screenshotSrc = currentView
    ? (isDark ? currentView.screenshot_dark : currentView.screenshot_light)
    : '';

  // Theme toggle
  useEffect(() => {{
    document.body.classList.toggle('light', !isDark);
  }}, [isDark]);

  const handleHotspotClick = useCallback((hs) => {{
    setActiveHotspotId(hs.hotspot_id);
    setDrawerOpen(true);
  }}, []);

  const handleHotspotHover = useCallback((hs, e) => {{
    if (mode === 'free') {{
      setActiveHotspotId(hs.hotspot_id);
      setDrawerOpen(true);
    }}
    setHoveredHotspot({{ hs, x: e.clientX, y: e.clientY }});
  }}, [mode]);

  const closeDrawer = useCallback(() => {{
    setDrawerOpen(false);
    setActiveHotspotId(null);
  }}, []);

  const nextTab = () => setTabIndex(i => Math.min(i + 1, tabs.length - 1));
  const prevTab = () => setTabIndex(i => Math.max(i - 1, 0));

  const activeIdx = viewHotspots.findIndex(h => h.hotspot_id === activeHotspotId);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden relative">
      {{/* Floating Pill Nav - top center */}}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 pill rounded-full px-3 py-1.5"
           style={{{{ transform: drawerOpen ? 'translateX(calc(-50% - 190px))' : 'translateX(-50%)' , transition: 'transform 300ms cubic-bezier(0.32,0.72,0,1)' }}}}>
        <button onClick={{prevTab}} disabled={{tabIndex === 0}}
                className="text-sm opacity-60 hover:opacity-100 disabled:opacity-20 cursor-pointer disabled:cursor-default">
          &#8592;
        </button>
        <span className="text-sm font-semibold">{{TAB_TITLE[currentTab] || currentTab}}</span>
        <span className="text-xs text-secondary">{{tabIndex + 1}} / {{tabs.length}}</span>
        <button onClick={{nextTab}} disabled={{tabIndex === tabs.length - 1}}
                className="text-sm opacity-60 hover:opacity-100 disabled:opacity-20 cursor-pointer disabled:cursor-default">
          &#8594;
        </button>

        {{/* Sub-view selector (if tab has multiple views) */}}
        {{tabViews.length > 1 && (
          <div className="flex items-center gap-1 ml-2 pl-2 border-l border-subtle">
            {{tabViews.map((v, i) => (
              <button key={{v.view_id}} onClick={{() => {{ setViewIndex(i); setActiveHotspotId(null); setDrawerOpen(false); }}}}
                      className={{`text-xs px-2 py-0.5 rounded-full cursor-pointer ${{i === viewIndex ? 'bg-accent text-white' : 'text-secondary hover:text-white'}}`}}>
                {{v.variant === 'default' ? 'Default' : v.variant.charAt(0).toUpperCase() + v.variant.slice(1)}}
              </button>
            ))}}
          </div>
        )}}
      </div>

      {{/* Screenshot Stage */}}
      <div className="flex-1 min-h-0 flex flex-col items-center p-4 pt-14 pb-12 overflow-hidden"
           style={{{{ paddingRight: drawerOpen ? '396px' : '16px', transition: 'padding-right 300ms cubic-bezier(0.32,0.72,0,1)' }}}}>
        <div ref={{containerRef}} className="screenshot-stage w-full max-h-full rounded-lg"
             style={{{{ border: '1px solid', borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}}}>
          <div style={{{{ position: 'relative', width: '100%' }}}}>
            <img src={{screenshotSrc}} alt={{`${{currentTab}} dashboard`}}
                 style={{{{ width: '100%', display: 'block' }}}} draggable="false"/>

            {{/* Hotspot overlay — matches image exactly */}}
            <div style={{{{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none' }}}}>
              {{viewHotspots.map((hs, idx) => {{
                const isActive = activeHotspotId === hs.hotspot_id;
                return (
                  <button key={{hs.hotspot_id}}
                          className={{`absolute hotspot-ring rounded-lg cursor-pointer ${{isActive ? 'active' : ''}}`}}
                          style={{{{
                            left: `${{hs.bbox_pct.x}}%`,
                            top: `${{hs.bbox_pct.y}}%`,
                            width: `${{hs.bbox_pct.width}}%`,
                            height: `${{hs.bbox_pct.height}}%`,
                            zIndex: hs.z_index,
                            pointerEvents: 'auto',
                          }}}}
                          onClick={{() => handleHotspotClick(hs)}}
                          onMouseEnter={{(e) => handleHotspotHover(hs, e)}}
                          onMouseLeave={{() => setHoveredHotspot(null)}}
                          aria-label={{`${{idx + 1}}. ${{hs.tooltip_summary.title}}`}}>
                    <span className="hotspot-badge">{{idx + 1}}</span>
                    {{isActive && <span className="pulse rounded-lg"></span>}}
                  </button>
                );
              }})}}
            </div>
          </div>
        </div>
      </div>

      {{/* Tooltip on hover */}}
      {{hoveredHotspot && !drawerOpen && (
        <div className="tooltip"
             style={{{{ top: Math.max(10, hoveredHotspot.y - 120), left: Math.min(hoveredHotspot.x + 16, window.innerWidth - 300) }}}}>
          <div className="font-bold mb-1">{{hoveredHotspot.hs.tooltip_summary.title}}</div>
          <div className="opacity-70 mb-1">{{hoveredHotspot.hs.tooltip_summary.business_question}}</div>
          <div style={{{{ color: '#fbbf24' }}}} className="font-semibold text-xs">{{hoveredHotspot.hs.tooltip_summary.kpi_name}}</div>
        </div>
      )}}

      {{/* Slide-over Drawer */}}
      <div className={{`fixed top-0 right-0 bottom-0 w-[380px] drawer z-40 overflow-y-auto ${{drawerOpen ? 'drawer-visible' : 'drawer-enter'}}`}}
           style={{{{ display: drawerOpen || activeStory ? 'block' : 'none' }}}}>
        {{activeStory && (
          <div className="p-5">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h2 className="text-base font-semibold">{{activeStory.title}}</h2>
                <p className="text-xs text-secondary mt-1">{{activeStory.kpi_name}}</p>
              </div>
              <button onClick={{closeDrawer}} className="text-secondary hover:text-white cursor-pointer text-lg">&#10005;</button>
            </div>
            <div className="border-t border-subtle mb-4"></div>

            {{/* Stepper */}}
            <div className="flex items-center gap-2 mb-4">
              {{viewHotspots.map((hs, idx) => (
                <button key={{hs.hotspot_id}}
                        onClick={{() => handleHotspotClick(hs)}}
                        className={{`w-7 h-7 rounded-full text-xs font-bold cursor-pointer ${{
                          activeHotspotId === hs.hotspot_id
                            ? 'bg-accent text-white'
                            : 'border border-subtle text-secondary hover:text-white'
                        }}`}}>
                  {{idx + 1}}
                </button>
              ))}}
            </div>

            <Section label="Why It Exists" text={{activeStory.why_this_exists}} />
            <Section label="What It Means" text={{activeStory.kpi_or_chart_definition}} />
            <Section label="Formula" text={{activeStory.formula}} isCode />
            <Section label="Inputs" text={{Array.isArray(activeStory.inputs) ? activeStory.inputs.join(', ') : activeStory.inputs}} />
            <Section label="Good vs Risk" text={{activeStory.how_to_read_good_vs_risk}} />
            <Section label="Decision Supported" text={{activeStory.decision_supported}} />
            <Section label="Recommended Action" text={{activeStory.recommended_next_action}} />
            <Section label="Misinterpretation Risk" text={{activeStory.misinterpretation_risks}} />
            <Section label="Caveat" text={{activeStory.data_freshness_or_caveats}} />
            {{activeStory.worked_example && activeStory.worked_example !== 'N/A' && (
              <Section label="Worked Example" text={{activeStory.worked_example}} />
            )}}
          </div>
        )}}
      </div>

      {{/* Floating Toolbar - bottom right */}}
      <div className="absolute bottom-3 right-4 z-30 flex items-center gap-2"
           style={{{{ right: drawerOpen ? '396px' : '16px', transition: 'right 300ms cubic-bezier(0.32,0.72,0,1)' }}}}>
        {{/* Theme toggle */}}
        <button onClick={{() => setIsDark(d => !d)}} className="pill rounded-full px-3 py-1.5 flex items-center gap-2 cursor-pointer"
                title={{isDark ? 'Switch to light mode' : 'Switch to dark mode'}}>
          <span className={{isDark ? 'opacity-40' : 'text-amber-400'}}>&#9788;</span>
          <div className="w-8 h-4 rounded-full relative" style={{{{ background: isDark ? '#333' : '#d1d5db' }}}}>
            <div className="w-3 h-3 rounded-full bg-white absolute top-0.5 transition-all duration-200"
                 style={{{{ left: isDark ? '18px' : '2px' }}}}></div>
          </div>
          <span className={{isDark ? 'text-blue-300' : 'opacity-40'}}>&#9790;</span>
        </button>
        {{/* Mode toggle */}}
        <button onClick={{() => setMode(m => m === 'guided' ? 'free' : 'guided')}}
                className="pill rounded-full px-3 py-1.5 text-xs text-secondary cursor-pointer">
          {{mode === 'guided' ? 'Guided' : 'Free Hover'}}
        </button>
        {{/* Counter */}}
        {{activeIdx >= 0 && (
          <div className="pill rounded-full px-3 py-1.5 text-xs text-secondary">
            {{activeIdx + 1}} / {{viewHotspots.length}}
          </div>
        )}}
      </div>

      {{/* Progress Dots - bottom center */}}
      <div className="absolute bottom-3.5 left-1/2 -translate-x-1/2 z-30 flex gap-1.5"
           style={{{{ transform: drawerOpen ? 'translateX(calc(-50% - 190px))' : 'translateX(-50%)', transition: 'transform 300ms cubic-bezier(0.32,0.72,0,1)' }}}}>
        {{tabs.map((t, i) => (
          <button key={{t}} onClick={{() => setTabIndex(i)}}
                  className={{`w-2 h-2 rounded-full cursor-pointer transition-colors ${{i === tabIndex ? 'bg-accent' : 'bg-gray-600 hover:bg-gray-400'}}`}}
                  title={{TAB_TITLE[t] || t}} />
        ))}}
      </div>
    </div>
  );
}}

function Section({{ label, text, isCode }}) {{
  if (!text || text === 'N/A') return null;
  return (
    <div className="mb-3">
      <div className="section-label">{{label}}</div>
      {{isCode ? (
        <pre className="formula-block whitespace-pre-wrap">{{text}}</pre>
      ) : (
        <p className="text-sm leading-relaxed text-secondary">{{text}}</p>
      )}}
    </div>
  );
}}

ReactDOM.render(<App />, document.getElementById('root'));
</script>
</body>
</html>"""

    write_text(output_dir / "index.html", html)


def _legacy_write_next_site_source(interactive_src: Path) -> None:
    """Legacy Next.js multi-page site generator. Kept for reference."""
    write_text(
        interactive_src / "package.json",
        """{
  "name": "dashboard-walkthrough",
  "private": true,
  "version": "1.0.0",
  "scripts": {
    "dev": "next dev -p 4400",
    "build": "next build"
  },
  "dependencies": {
    "@radix-ui/react-tooltip": "^1.1.8",
    "framer-motion": "^12.23.16",
    "next": "^15.5.3",
    "react": "^19.1.1",
    "react-dom": "^19.1.1"
  }
}
""",
    )

    write_text(
        interactive_src / "next.config.mjs",
        """/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
""",
    )

    write_text(
        interactive_src / "pages" / "_app.js",
        """import '../styles/globals.css';

export default function App({ Component, pageProps }) {
  return <Component {...pageProps} />;
}
""",
    )

    write_text(
        interactive_src / "pages" / "index.js",
        """import { useEffect } from 'react';

export default function HomeRedirect() {
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (window.location.protocol === 'file:') {
      window.location.replace('./tab/home/index.html');
      return;
    }
    window.location.replace('/tab/home');
  }, []);

  return (
    <main className=\"boot\">
      <h1>Interactive Dashboard Walkthrough</h1>
      <p>Redirecting to Home tab walkthrough…</p>
      <a href=\"./tab/home/index.html\">Open manually</a>
    </main>
  );
}
""",
    )

    write_text(
        interactive_src / "pages" / "tab" / "[tab].js",
        """import fs from 'fs';
import path from 'path';
import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import * as Tooltip from '@radix-ui/react-tooltip';

const TAB_TITLE = {
  home: 'Home',
  'sales-impact': 'Sales Impact',
  'response-curves': 'Response Curves',
  'budget-allocator': 'Budget Allocator',
  experiment: 'Simulator',
  insights: 'Insights',
  settings: 'Settings',
  geography: 'Geography',
};

export async function getStaticPaths() {
  const dataPath = path.join(process.cwd(), 'public', 'data', 'hotspot_manifest.json');
  const hotspotManifest = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
  const paths = hotspotManifest.tabs.map((tab) => ({ params: { tab } }));
  return { paths, fallback: false };
}

export async function getStaticProps({ params }) {
  const hotspotPath = path.join(process.cwd(), 'public', 'data', 'hotspot_manifest.json');
  const storyPath = path.join(process.cwd(), 'public', 'data', 'story_content.json');

  const hotspotManifest = JSON.parse(fs.readFileSync(hotspotPath, 'utf8'));
  const storyContent = JSON.parse(fs.readFileSync(storyPath, 'utf8'));

  const tab = params.tab;
  const tabStates = hotspotManifest.states.filter((s) => s.tab === tab);
  const tabStateIds = new Set(tabStates.map((s) => s.state_id));
  const tabHotspots = hotspotManifest.hotspots
    .filter((h) => tabStateIds.has(h.state_id))
    .sort((a, b) => {
      if (a.state_id === b.state_id) return a.order_in_state - b.order_in_state;
      return a.state_id.localeCompare(b.state_id);
    });

  const storyRows = storyContent.rows.filter((r) => tabStateIds.has(r.state_id));

  return {
    props: {
      tab,
      tabs: hotspotManifest.tabs,
      canonicalContext: hotspotManifest.canonical_context,
      tabStates,
      tabHotspots,
      storyRows,
    },
  };
}

function stateLabel(state) {
  return state
    .replace('light-', 'Light: ')
    .replace('light', 'Light')
    .replace('dark', 'Dark')
    .replace('-', ' ');
}

export default function TabWalkthroughPage({
  tab,
  tabs,
  canonicalContext,
  tabStates,
  tabHotspots,
  storyRows,
}) {
  const prefersReducedMotion = useReducedMotion();
  const isFileMode = typeof window !== 'undefined' && window.location.protocol === 'file:';

  const toTabHref = (targetTab) => {
    if (!targetTab) return '#';
    return isFileMode ? `../${targetTab}/index.html` : `/tab/${targetTab}`;
  };

  const toAssetHref = (assetPath) => {
    const clean = String(assetPath || '').replace(/^\\/+/, '');
    return isFileMode ? `../../${clean}` : `/${clean}`;
  };

  const defaultStateId = useMemo(() => {
    const lightPrimary = tabStates.find((s) => s.state === 'light' || s.state.endsWith('revenue') || s.state.endsWith('optimize') || s.state.endsWith('advanced'));
    return (lightPrimary || tabStates[0])?.state_id;
  }, [tabStates]);

  const [selectedStateId, setSelectedStateId] = useState(defaultStateId);
  const [mode, setMode] = useState('guided');
  const [guidedIndex, setGuidedIndex] = useState(0);
  const [activeHotspotId, setActiveHotspotId] = useState(null);
  const [visited, setVisited] = useState({});
  const [focusIndex, setFocusIndex] = useState(0);
  const [mobilePanelOpen, setMobilePanelOpen] = useState(true);

  const hotspotRefs = useRef([]);

  const stateMap = useMemo(() => {
    const map = {};
    for (const st of tabStates) map[st.state_id] = st;
    return map;
  }, [tabStates]);

  const storyMap = useMemo(() => {
    const map = {};
    for (const row of storyRows) map[row.component_id] = row;
    return map;
  }, [storyRows]);

  const currentState = stateMap[selectedStateId] || tabStates[0];
  const stateHotspots = useMemo(() => {
    return tabHotspots
      .filter((h) => h.state_id === selectedStateId)
      .sort((a, b) => a.order_in_state - b.order_in_state);
  }, [tabHotspots, selectedStateId]);

  useEffect(() => {
    setGuidedIndex(0);
    setFocusIndex(0);
    const first = stateHotspots[0]?.hotspot_id || null;
    setActiveHotspotId(first);
  }, [selectedStateId]);

  useEffect(() => {
    if (mode !== 'guided') return;
    const hs = stateHotspots[guidedIndex];
    if (!hs) return;
    setActiveHotspotId(hs.hotspot_id);
    setMobilePanelOpen(true);
  }, [guidedIndex, mode, stateHotspots]);

  const activeHotspot = stateHotspots.find((h) => h.hotspot_id === activeHotspotId) || stateHotspots[0] || null;
  const activeStory = activeHotspot ? storyMap[activeHotspot.component_id] : null;

  const currentTabIndex = tabs.indexOf(tab);
  const prevTab = currentTabIndex > 0 ? tabs[currentTabIndex - 1] : null;
  const nextTab = currentTabIndex < tabs.length - 1 ? tabs[currentTabIndex + 1] : null;

  const stageKeyDown = (e) => {
    if (!stateHotspots.length) return;

    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      const next = Math.min(focusIndex + 1, stateHotspots.length - 1);
      setFocusIndex(next);
      hotspotRefs.current[next]?.focus();
      return;
    }

    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = Math.max(focusIndex - 1, 0);
      setFocusIndex(prev);
      hotspotRefs.current[prev]?.focus();
      return;
    }

    if (e.key === 'Enter') {
      e.preventDefault();
      const hs = stateHotspots[focusIndex];
      if (!hs) return;
      setActiveHotspotId(hs.hotspot_id);
      setVisited((v) => ({ ...v, [hs.hotspot_id]: true }));
      setMobilePanelOpen(true);
      if (mode === 'guided') {
        const idx = stateHotspots.findIndex((x) => x.hotspot_id === hs.hotspot_id);
        if (idx >= 0) setGuidedIndex(idx);
      }
      return;
    }

    if (e.key === 'Escape') {
      const el = document.activeElement;
      if (el && typeof el.blur === 'function') el.blur();
      return;
    }
  };

  const activateHotspot = (hs, idx) => {
    setActiveHotspotId(hs.hotspot_id);
    setVisited((v) => ({ ...v, [hs.hotspot_id]: true }));
    setFocusIndex(idx);
    setMobilePanelOpen(true);
    if (mode === 'guided') setGuidedIndex(idx);
  };

  const nextStep = () => {
    if (!stateHotspots.length) return;
    setGuidedIndex((i) => Math.min(i + 1, stateHotspots.length - 1));
  };

  const prevStep = () => {
    if (!stateHotspots.length) return;
    setGuidedIndex((i) => Math.max(i - 1, 0));
  };

  const progressPct = stateHotspots.length
    ? ((stateHotspots.findIndex((h) => h.hotspot_id === activeHotspotId) + 1) / stateHotspots.length) * 100
    : 0;

  const liveUrl = activeHotspot?.live_dashboard_url || `http://127.0.0.1:3000/?tab=${tab}`;

  return (
    <div className=\"walk-page\">
      <header className=\"topbar\">
        <div>
          <h1>{TAB_TITLE[tab] || tab} Walkthrough</h1>
          <p className=\"sub\">Hover any hotspot for context, then click to open the full business interpretation.</p>
          <div className=\"chips\">
            <span className=\"chip\">{canonicalContext.country}</span>
            <span className=\"chip\">{canonicalContext.product}</span>
            <span className=\"chip\">{canonicalContext.year}</span>
            <span className=\"chip\">{canonicalContext.version}</span>
          </div>
        </div>
        <div className=\"top-actions\">
          <div className=\"mode-switch\" role=\"tablist\" aria-label=\"Interaction mode\">
            <button className={mode === 'guided' ? 'active' : ''} onClick={() => setMode('guided')}>Guided</button>
            <button className={mode === 'free' ? 'active' : ''} onClick={() => setMode('free')}>Free Hover</button>
          </div>
          <a className=\"live-link\" href={liveUrl} target=\"_blank\" rel=\"noreferrer\">Open live dashboard</a>
        </div>
      </header>

      <nav className=\"tab-nav\" aria-label=\"Tab pager\">
        <div>{prevTab ? <a href={toTabHref(prevTab)}>← {TAB_TITLE[prevTab]}</a> : <span />} </div>
        <div className=\"tab-counter\">Tab {currentTabIndex + 1} / {tabs.length}</div>
        <div>{nextTab ? <a href={toTabHref(nextTab)}>{TAB_TITLE[nextTab]} →</a> : <span />} </div>
      </nav>

      <div className=\"state-switch\">
        {tabStates.map((st) => (
          <button
            key={st.state_id}
            className={selectedStateId === st.state_id ? 'active' : ''}
            onClick={() => setSelectedStateId(st.state_id)}
          >
            {stateLabel(st.state)}
          </button>
        ))}
      </div>

      <div className=\"content-grid\">
        <section className=\"stage-card\" aria-label=\"Hotspot stage\">
          <div className=\"progress-wrap\">
            <div className=\"progress-bar\"><div style={{ width: `${progressPct}%` }} /></div>
            <span>{stateHotspots.findIndex((h) => h.hotspot_id === activeHotspotId) + 1} / {stateHotspots.length} components</span>
          </div>

          <div className=\"stage\" tabIndex={0} onKeyDown={stageKeyDown}>
            <AnimatePresence mode=\"wait\">
              <motion.img
                key={currentState.state_id}
                src={toAssetHref(currentState.screenshot_public)}
                alt={`${tab} ${currentState.state}`}
                initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: prefersReducedMotion ? 0 : -8 }}
                transition={{ duration: prefersReducedMotion ? 0 : 0.25 }}
              />
            </AnimatePresence>

            <Tooltip.Provider delayDuration={110}>
              {stateHotspots.map((hs, idx) => {
                const isActive = activeHotspotId === hs.hotspot_id;
                const isVisited = Boolean(visited[hs.hotspot_id]);
                return (
                  <Tooltip.Root key={hs.hotspot_id}>
                    <Tooltip.Trigger asChild>
                      <motion.button
                        ref={(el) => { hotspotRefs.current[idx] = el; }}
                        className={`hotspot ${isActive ? 'is-active' : ''} ${isVisited ? 'is-visited' : ''}`}
                        style={{
                          left: `${hs.bbox_pct.x}%`,
                          top: `${hs.bbox_pct.y}%`,
                          width: `${hs.bbox_pct.width}%`,
                          height: `${hs.bbox_pct.height}%`,
                          zIndex: hs.z_index,
                        }}
                        initial={{ opacity: 0, scale: prefersReducedMotion ? 1 : 0.92 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ duration: prefersReducedMotion ? 0 : 0.2, delay: prefersReducedMotion ? 0 : idx * 0.035 }}
                        onMouseEnter={() => { if (mode === 'free') setActiveHotspotId(hs.hotspot_id); }}
                        onFocus={() => setFocusIndex(idx)}
                        onClick={() => activateHotspot(hs, idx)}
                        aria-label={`${idx + 1}. ${hs.tooltip_summary.title}`}
                      >
                        <span className=\"hotspot-pill\">{idx + 1}</span>
                        {isActive && !prefersReducedMotion ? (
                          <motion.span
                            className=\"hotspot-pulse\"
                            initial={{ opacity: 0.35, scale: 1 }}
                            animate={{ opacity: 0, scale: 1.07 }}
                            transition={{ duration: 1.1, repeat: Infinity }}
                          />
                        ) : null}
                      </motion.button>
                    </Tooltip.Trigger>
                    <Tooltip.Portal>
                      <Tooltip.Content sideOffset={8} className=\"tt\" side=\"top\">
                        <div className=\"tt-title\">{hs.tooltip_summary.title}</div>
                        <div className=\"tt-q\">{hs.tooltip_summary.business_question}</div>
                        <div className=\"tt-kpi\">{hs.tooltip_summary.kpi_name}</div>
                        <div className=\"tt-v\">{hs.tooltip_summary.one_line_value}</div>
                        <Tooltip.Arrow className=\"tt-arrow\" />
                      </Tooltip.Content>
                    </Tooltip.Portal>
                  </Tooltip.Root>
                );
              })}
            </Tooltip.Provider>
          </div>

          <div className=\"stepper\" aria-label=\"Guided steps\">
            <button onClick={prevStep} disabled={!stateHotspots.length || guidedIndex === 0}>Previous</button>
            <div className=\"step-chips\">
              {stateHotspots.map((hs, idx) => (
                <button
                  key={hs.hotspot_id}
                  className={activeHotspotId === hs.hotspot_id ? 'active' : ''}
                  onClick={() => activateHotspot(hs, idx)}
                >
                  {idx + 1}
                </button>
              ))}
            </div>
            <button onClick={nextStep} disabled={!stateHotspots.length || guidedIndex >= stateHotspots.length - 1}>Next</button>
          </div>
        </section>

        <AnimatePresence>
          {activeStory ? (
            <motion.aside
              key={activeStory.component_id}
              className={`detail-panel ${mobilePanelOpen ? 'mobile-open' : ''}`}
              initial={{ opacity: 0, x: prefersReducedMotion ? 0 : 16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: prefersReducedMotion ? 0 : 16 }}
              transition={{ type: 'spring', damping: 25, stiffness: 260 }}
            >
              <div className=\"panel-head\">
                <div>
                  <h2>{activeStory.title}</h2>
                  <p>{activeStory.kpi_name}</p>
                </div>
                <button className=\"mobile-close\" onClick={() => setMobilePanelOpen(false)} aria-label=\"Close details\">✕</button>
              </div>

              <div className=\"panel-body\">
                <section>
                  <h3>Why It Exists</h3>
                  <p>{activeStory.why_this_exists}</p>
                </section>
                <section>
                  <h3>What It Means</h3>
                  <p>{activeStory.kpi_or_chart_definition}</p>
                </section>
                <section>
                  <h3>Formula</h3>
                  <pre>{activeStory.formula}</pre>
                </section>
                <section>
                  <h3>Inputs</h3>
                  <p>{Array.isArray(activeStory.inputs) ? activeStory.inputs.join(', ') : activeStory.inputs}</p>
                </section>
                <section>
                  <h3>How To Read (Good vs Risk)</h3>
                  <p>{activeStory.how_to_read_good_vs_risk}</p>
                </section>
                <section>
                  <h3>Decision Supported</h3>
                  <p>{activeStory.decision_supported}</p>
                </section>
                <section>
                  <h3>Recommended Action</h3>
                  <p>{activeStory.recommended_next_action}</p>
                </section>
                <section>
                  <h3>Misinterpretation Risk</h3>
                  <p>{activeStory.misinterpretation_risks}</p>
                </section>
                <section>
                  <h3>Caveat</h3>
                  <p>{activeStory.data_freshness_or_caveats}</p>
                </section>
                {activeStory.worked_example && activeStory.worked_example !== 'N/A' ? (
                  <section>
                    <h3>Worked Example</h3>
                    <p>{activeStory.worked_example}</p>
                  </section>
                ) : null}
              </div>
            </motion.aside>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  );
}
""",
    )

    write_text(
        interactive_src / "styles" / "globals.css",
        """:root {
  --bg-a: #eff7f6;
  --bg-b: #f8fafb;
  --ink: #10212b;
  --muted: #4f6773;
  --line: #cfe0e7;
  --card: rgba(255, 255, 255, 0.82);
  --accent: #0f8b8d;
  --accent-2: #d1495b;
  --focus: #1f7ae0;
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; color: var(--ink); }
body {
  background:
    radial-gradient(circle at 12% 10%, #d8f2ee 0%, transparent 40%),
    radial-gradient(circle at 88% 0%, #fbe8df 0%, transparent 36%),
    linear-gradient(160deg, var(--bg-a), var(--bg-b));
}

a { color: #0e5b9a; text-decoration: none; }
a:hover { text-decoration: underline; }

.boot { padding: 40px; }

.walk-page {
  min-height: 100vh;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 16px 18px;
  backdrop-filter: blur(10px);
}

.topbar h1 { margin: 0; font-size: 30px; letter-spacing: -0.02em; }
.topbar .sub { margin: 6px 0 10px; color: var(--muted); }

.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  font-size: 12px;
}

.top-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.mode-switch {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: 999px;
  overflow: hidden;
}

.mode-switch button {
  border: none;
  padding: 8px 14px;
  background: transparent;
  cursor: pointer;
  color: var(--muted);
  font-weight: 600;
}
.mode-switch button.active {
  background: var(--accent);
  color: white;
}

.live-link {
  border: 1px solid rgba(15, 139, 141, 0.35);
  background: rgba(15, 139, 141, 0.08);
  color: #0a5f61;
  padding: 8px 12px;
  border-radius: 10px;
  font-weight: 600;
}

.tab-nav {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
}

.tab-nav > div:nth-child(1) { justify-self: start; }
.tab-nav > div:nth-child(2) { justify-self: center; color: var(--muted); font-size: 13px; }
.tab-nav > div:nth-child(3) { justify-self: end; }

.state-switch {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.state-switch button {
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.65);
  color: var(--muted);
  border-radius: 999px;
  padding: 6px 12px;
  font-weight: 600;
  cursor: pointer;
}

.state-switch button.active {
  color: white;
  border-color: transparent;
  background: linear-gradient(135deg, #0f8b8d, #23789d);
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: 14px;
  align-items: start;
}

.stage-card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 14px;
  backdrop-filter: blur(10px);
}

.progress-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.progress-wrap span { font-size: 12px; color: var(--muted); min-width: 120px; text-align: right; }
.progress-bar {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: rgba(16, 33, 43, 0.1);
  overflow: hidden;
}
.progress-bar > div {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #0f8b8d, #e76f51);
  transition: width 220ms ease;
}

.stage {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: auto;
  max-height: calc(100vh - 310px);
  background: white;
  outline: none;
}

.stage img {
  display: block;
  width: 100%;
  height: auto;
}

.hotspot {
  position: absolute;
  border: 2px solid rgba(15, 139, 141, 0.85);
  border-radius: 12px;
  background: rgba(15, 139, 141, 0.12);
  cursor: pointer;
  transition: all 160ms ease;
}

.hotspot:hover,
.hotspot:focus-visible {
  border-color: rgba(209, 73, 91, 0.95);
  background: rgba(209, 73, 91, 0.14);
  box-shadow: 0 0 0 3px rgba(31, 122, 224, 0.24);
}

.hotspot.is-active {
  border-color: rgba(209, 73, 91, 1);
  background: rgba(209, 73, 91, 0.16);
}

.hotspot.is-visited:not(.is-active) {
  border-color: rgba(15, 139, 141, 0.6);
}

.hotspot-pill {
  position: absolute;
  top: -10px;
  left: -10px;
  min-width: 24px;
  height: 24px;
  border-radius: 999px;
  border: 2px solid white;
  background: #d1495b;
  color: white;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
}

.hotspot-pulse {
  position: absolute;
  inset: -4px;
  border-radius: 14px;
  border: 2px solid rgba(209, 73, 91, 0.6);
  pointer-events: none;
}

.tt {
  max-width: 280px;
  background: rgba(8, 24, 34, 0.95);
  color: #f5fafb;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.45;
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.35);
}

.tt-title { font-weight: 700; margin-bottom: 4px; }
.tt-q { color: #d3e5ec; margin-bottom: 5px; }
.tt-kpi { color: #ffd7a2; font-weight: 600; margin-bottom: 4px; }
.tt-v { color: #bdeff1; }
.tt-arrow { fill: rgba(8, 24, 34, 0.95); }

.stepper {
  margin-top: 10px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
}

.stepper > button {
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.7);
  border-radius: 10px;
  padding: 8px 10px;
  font-weight: 600;
  cursor: pointer;
}
.stepper > button:disabled { opacity: 0.45; cursor: not-allowed; }

.step-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.step-chips button {
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.72);
  border-radius: 999px;
  min-width: 28px;
  height: 28px;
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  cursor: pointer;
}

.step-chips button.active {
  color: white;
  border-color: transparent;
  background: linear-gradient(135deg, #d1495b, #0f8b8d);
}

.detail-panel {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 14px;
  backdrop-filter: blur(10px);
  max-height: calc(100vh - 215px);
  overflow: auto;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 10px;
}

.panel-head h2 { margin: 0; font-size: 20px; letter-spacing: -0.01em; }
.panel-head p { margin: 4px 0 0; color: var(--muted); }
.mobile-close { display: none; border: none; background: transparent; font-size: 20px; cursor: pointer; color: var(--muted); }

.panel-body section { margin-top: 12px; }
.panel-body h3 {
  margin: 0 0 5px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #4e6470;
}
.panel-body p { margin: 0; line-height: 1.55; color: #132732; }
.panel-body pre {
  margin: 0;
  white-space: pre-wrap;
  background: rgba(16, 33, 43, 0.06);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

@media (max-width: 1200px) {
  .content-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-panel {
    position: fixed;
    left: 12px;
    right: 12px;
    bottom: 12px;
    max-height: 55vh;
    transform: translateY(120%);
    transition: transform 230ms ease;
    z-index: 70;
    box-shadow: 0 20px 50px rgba(0,0,0,0.25);
  }

  .detail-panel.mobile-open {
    transform: translateY(0);
  }

  .mobile-close {
    display: inline-block;
  }

  .stage {
    max-height: calc(100vh - 360px);
  }
}

@media (max-width: 920px) {
  .walk-page { padding: 12px; }
  .topbar { flex-direction: column; }
  .top-actions { align-items: flex-start; width: 100%; }
  .tab-nav { grid-template-columns: 1fr; gap: 5px; }
  .tab-nav > div { justify-self: start !important; }
}
""",
    )


def build_final_qa(run_dir: Path) -> dict[str, Any]:
    hotspot_manifest = read_json(run_dir / "manifests" / "hotspot_manifest.json")
    story_content = read_json(run_dir / "manifests" / "story_content.json")

    static_dir = run_dir / "interactive-site-static"
    tabs = hotspot_manifest["tabs"]
    hotspots = hotspot_manifest["hotspots"]
    stories = story_content["rows"]

    story_ids = {row["component_id"] for row in stories}

    bbox_issues = []
    for hs in hotspots:
        b = hs["bbox_pct"]
        if b["x"] < 0 or b["y"] < 0 or b["width"] <= 0 or b["height"] <= 0:
            bbox_issues.append(hs["hotspot_id"])
        if b["x"] + b["width"] > 100.2 or b["y"] + b["height"] > 100.2:
            bbox_issues.append(hs["hotspot_id"])

    missing_story = [hs["component_id"] for hs in hotspots if hs["component_id"] not in story_ids]

    route_missing = []
    if not (static_dir / "index.html").exists():
        route_missing.append("index.html")
    for tab in tabs:
        route1 = static_dir / "tab" / tab / "index.html"
        route2 = static_dir / "tab" / f"{tab}.html"
        if not route1.exists() and not route2.exists():
            route_missing.append(f"tab/{tab}")

    screenshot_missing = []
    for st in hotspot_manifest["states"]:
        shot = static_dir / st["screenshot_public"].lstrip("/")
        if not shot.exists():
            screenshot_missing.append(st["screenshot_public"])

    bad_paths = []
    try:
        status = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(run_dir),
        )
        for line in status.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split()
            p = parts[-1]
            if not p.startswith("temp/"):
                bad_paths.append(p)
    except (FileNotFoundError, OSError):
        pass  # git not available or not in a repo - skip hygiene check

    checks = {
        "tab_routes": {"ok": len(route_missing) == 0, "missing": route_missing},
        "bbox_validity": {"ok": len(bbox_issues) == 0, "issues": sorted(set(bbox_issues))},
        "story_coverage": {"ok": len(missing_story) == 0, "missing_components": sorted(set(missing_story))},
        "screenshot_assets": {"ok": len(screenshot_missing) == 0, "missing": sorted(set(screenshot_missing))},
        "hygiene_outside_temp": {"ok": len(bad_paths) == 0, "bad_paths": sorted(set(bad_paths))},
        "counts": {
            "ok": len(hotspots) > 0 and len(stories) > 0,
            "hotspots": len(hotspots),
            "stories": len(stories),
            "tabs": len(tabs),
            "states": len(hotspot_manifest["states"]),
        },
    }

    all_ok = all(v["ok"] for v in checks.values())

    report = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "run_dir": str(run_dir),
        "all_checks_passed": all_ok,
        "checks": checks,
    }
    return report


def rewrite_static_html_for_file_mode(static_dir: Path) -> None:
    for html_file in static_dir.rglob("*.html"):
        rel_parent = html_file.parent.relative_to(static_dir)
        depth = len(rel_parent.parts)
        prefix = "../" * depth if depth > 0 else "./"

        text = html_file.read_text(encoding="utf-8")
        updated = text
        updated = updated.replace('"/_next/', f'"{prefix}_next/')
        updated = updated.replace("'/_next/", f"'{prefix}_next/")
        updated = re.sub(
            r'href="/tab/([^"/?#]+?)/?"',
            rf'href="{prefix}tab/\1/index.html"',
            updated,
        )
        updated = re.sub(
            r"href='/tab/([^'/?#]+?)/?'",
            rf"href='{prefix}tab/\1/index.html'",
            updated,
        )
        updated = updated.replace('"/screenshots/', f'"{prefix}screenshots/')
        updated = updated.replace("'/screenshots/", f"'{prefix}screenshots/")

        if updated != text:
            html_file.write_text(updated, encoding="utf-8")


def finalize_stage(run_dir: Path) -> dict[str, Any]:
    """Finalize: the SPA is already written by prepare_stage. Just run QA and write docs."""
    static_dst = run_dir / "interactive-site-static"

    if not (static_dst / "index.html").exists():
        raise SystemExit(
            f"index.html not found at {static_dst}. Run prepare stage first."
        )

    open_html = run_dir / "docs" / "INTERACTIVE_WALKTHROUGH_OPEN.html"
    write_text(
        open_html,
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="0; url=../interactive-site-static/index.html" />
  <title>MMM Decision Walkthrough</title>
  <script>
    window.location.replace("../interactive-site-static/index.html");
  </script>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background: #0b0c10;
      color: #f5f5f7;
    }
    a { color: #f5f5f7; }
  </style>
</head>
<body>
  <p>Redirecting to MMM Decision Walkthrough. <a href="../interactive-site-static/index.html">Open now</a></p>
</body>
</html>
""",
    )

    report = build_final_qa(run_dir)
    report_path = run_dir / "manifests" / "qa_report_interactive.json"
    write_json(report_path, report)

    walkthrough_md = run_dir / "docs" / "FINAL_WALKTHROUGH.md"
    write_text(
        walkthrough_md,
        f"""# Final Walkthrough: Interactive Dashboard Documentation

## Run
- Run directory: `{run_dir}`
- Generated: `{dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}`

## Deliverables
- Interactive entry: `{open_html}`
- Single-page app: `{static_dst / 'index.html'}`
- Screenshots: `{static_dst / 'screenshots'}`
- Hotspot manifest: `{run_dir / 'manifests' / 'hotspot_manifest.json'}`
- Story content: `{run_dir / 'manifests' / 'story_content.json'}`
- QA report: `{report_path}`

## QA Summary
- All checks passed: `{report['all_checks_passed']}`
- Tabs: `{report['checks']['counts']['tabs']}`
- States: `{report['checks']['counts']['states']}`
- Hotspots: `{report['checks']['counts']['hotspots']}`
- Story rows: `{report['checks']['counts']['stories']}`

## Architecture
- Single-page React SPA (index.html + screenshots/)
- No build step required — works from file:// protocol
- Synced dark/light theme toggle
- Viewport-locked layout with floating navigation
- shadcn/ui-inspired components via Tailwind CSS
""",
    )

    return {
        "open_entry": str(open_html),
        "static_export": str(static_dst),
        "qa_report": str(report_path),
        "all_checks_passed": report["all_checks_passed"],
    }


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (
        Path(args.manifest).resolve()
        if args.manifest
        else run_dir / "manifests" / "component_manifest.json"
    )

    if args.stage == "prepare":
        result = prepare_stage(run_dir, manifest_path)
    else:
        result = finalize_stage(run_dir)

    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
