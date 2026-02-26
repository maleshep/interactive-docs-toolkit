#!/usr/bin/env node

import fs from "fs";
import path from "path";
import { chromium } from "playwright";

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://127.0.0.1:3000";
const API_HEALTH_URL = process.env.API_HEALTH_URL || "http://127.0.0.1:8000/api/health";
const COUNTRY = process.env.COUNTRY || "France";
const PRODUCT = process.env.PRODUCT || "france_mavenclad_snowflake";
const YEAR = Number(process.env.YEAR || "2023");
const VERSION = process.env.VERSION || "latest";
const DATA_SOURCE = process.env.DATA_SOURCE || "snowflake";

const RUN_DIR =
  process.env.RUN_DIR ||
  "/Users/amank/Code/marketing-mix/temp/dashboard-docs/runs/latest";
const CLEAN_DIR = process.env.OUTPUT_DIR || path.join(RUN_DIR, "clean");
const MANIFEST_PATH =
  process.env.MANIFEST_PATH ||
  path.join(RUN_DIR, "manifests", "component_manifest.json");
const DEFAULT_CAPTURE_SPEC_PATH =
  "/Users/amank/Code/marketing-mix/temp/dashboard-docs/spec/capture_spec.json";
const CAPTURE_SPEC_FROM_ENV = process.env.CAPTURE_SPEC_PATH;
const CAPTURE_SPEC_PATH = CAPTURE_SPEC_FROM_ENV || DEFAULT_CAPTURE_SPEC_PATH;

const CANONICAL_QUERY = new URLSearchParams({
  country: COUNTRY,
  product: PRODUCT,
  year: String(YEAR),
  version: VERSION,
}).toString();

const DEFAULT_TAB_META = {
  home: {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/home/HomeTab.tsx",
    ui_role: "Home analytics section",
    business_meaning:
      "Summarizes top-line performance and routes users into the optimization workflow.",
    interactions:
      "Buttons navigate to downstream tabs and scenarios open Simulator context.",
    api_endpoints: [
      "/api/contributions",
      "/api/budget",
      "/api/scenarios",
      "/api/channel-mix",
      "/api/products-summary",
    ],
    upstream_artifacts: [
      "pareto_alldecomp_matrix.csv",
      "raw_data.csv",
      "model_stats.json",
      "pymc_uncertainty.json",
    ],
    fallback_behavior:
      "Shows spinner then no-data placeholders when upstream rows are missing.",
  },
  "sales-impact": {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/sales-impact/SalesImpactTab.tsx",
    ui_role: "Sales impact module",
    business_meaning:
      "Explains model quality and incremental channel contributions by period.",
    interactions:
      "Export/copy controls support audit handoff and offline checks.",
    api_endpoints: ["/api/contributions", "/api/model-stats"],
    upstream_artifacts: [
      "pareto_alldecomp_matrix.csv",
      "raw_data.csv",
      "model_stats.json",
    ],
    fallback_behavior:
      "Charts/tables become empty when contribution rows are unavailable.",
  },
  "response-curves": {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/response-curves/ResponseCurvesTab.tsx",
    ui_role: "Response curve analytics module",
    business_meaning:
      "Shows diminishing returns and marginal efficiency across spend ranges.",
    interactions:
      "Channel badges and metric toggles alter chart semantics and comparison context.",
    api_endpoints: ["/api/curves", "/api/pymc-insights"],
    upstream_artifacts: ["response_curve_points.json", "pymc_uncertainty.json"],
    fallback_behavior:
      "Displays loading skeleton then hides unsupported channel overlays.",
  },
  "budget-allocator": {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/budget-allocator/BudgetAllocatorTab.tsx",
    ui_role: "Budget allocator module",
    business_meaning:
      "Converts spend constraints into optimized allocation scenarios.",
    interactions:
      "Supports optimize and what-if modes, with export and downstream simulator handoff.",
    api_endpoints: ["/api/budget", "/api/allocator", "/api/experiment"],
    upstream_artifacts: [
      "raw_data.csv",
      "response_curve_points.json",
      "model_stats.json",
    ],
    fallback_behavior:
      "Falls back to current allocations when optimizer inputs are incomplete.",
  },
  experiment: {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/experiment/ExperimentOptimizerTab.tsx",
    ui_role: "Simulator module",
    business_meaning:
      "Evaluates baseline/imported/manual multiplier scenarios against response curves.",
    interactions: "Scenarios can be saved, loaded, deleted, and reset.",
    api_endpoints: ["/api/experiment", "/api/scenarios"],
    upstream_artifacts: [
      "response_curve_points.json",
      "model_stats.json",
      "scenario_store.json",
    ],
    fallback_behavior:
      "Shows loading state until experiment payload resolves.",
  },
  insights: {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/insights/InsightsTab.tsx",
    ui_role: "Insights module",
    business_meaning:
      "Provides confidence-aware recommendations, saturation signals, and diagnostic health checks.",
    interactions:
      "Tooltips and chart interactions clarify probabilistic model interpretation.",
    api_endpoints: ["/api/pymc-insights", "/api/model-stats", "/api/contributions"],
    upstream_artifacts: [
      "pymc_uncertainty.json",
      "model_stats.json",
      "pareto_alldecomp_matrix.csv",
    ],
    fallback_behavior:
      "Falls back to base MMM cards and locked placeholders when PyMC outputs are absent.",
  },
  settings: {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/system-flow/SystemFlowTab.tsx",
    ui_role: "Settings module",
    business_meaning:
      "Configures market/product/version/tier and exposes one-pager model diagnostics.",
    interactions:
      "Selectors and tier buttons change active context and geography availability.",
    api_endpoints: ["/api/flow", "/api/model-stats"],
    upstream_artifacts: [
      "model_selection.json",
      "model_stats.json",
      "pareto_aggregated.csv",
    ],
    fallback_behavior:
      "Degrades to placeholder model stats when selected artifacts are missing.",
  },
  geography: {
    source_file:
      "/Users/amank/Code/marketing-mix/apps/dashboard/components/features/geography/GeographyTab.tsx",
    ui_role: "Geography module",
    business_meaning:
      "Surfaces territory-level effect heterogeneity and comparison signals.",
    interactions:
      "Map, table, and channel filters are linked for exploratory diagnosis.",
    api_endpoints: [
      "/api/territory-effects",
      "/api/territory-contributions",
      "/api/products-summary",
    ],
    upstream_artifacts: [
      "territory_effects.json",
      "territory_contributions.json",
      "model_stats.json",
    ],
    fallback_behavior:
      "If no territory payload exists, advanced map/table content remains empty.",
  },
  dark: {
    source_file: "/Users/amank/Code/marketing-mix/apps/dashboard/pages/index.tsx",
    ui_role: "Dark-mode parity overview",
    business_meaning: "Validates readability and layout parity in dark theme.",
    interactions: "None",
    api_endpoints: [],
    upstream_artifacts: [],
    fallback_behavior: "Inherits each tab's light-mode fallback behavior.",
  },
};

const DEFAULT_STATES = [
  {
    state_id: "home-light",
    tab: "home",
    nav_label: "Home",
    expected_text: "Dashboard Overview",
    state: "light",
    components: [
      {
        component_id: "TAB_HOME_OVERVIEW_SHELL",
        section: "tab-overview",
        anchors: ["Dashboard Overview"],
        optional: true,
        missing_reason:
          "Overview title can be masked by initial render timing; downstream component hotspots still captured.",
      },
      {
        component_id: "TAB_HOME_KPI_ROW",
        section: "kpi-row",
        anchors: ["Total Spend"],
      },
      {
        component_id: "TAB_HOME_ACTIONS_SCENARIOS",
        section: "quick-actions-and-scenarios",
        anchors: ["Quick Actions"],
      },
      {
        component_id: "TAB_HOME_MONTHLY_TREND",
        section: "monthly-trend",
        anchors: ["Monthly Incremental Sales Trend"],
      },
      {
        component_id: "TAB_HOME_CHANNEL_MIX",
        section: "channel-mix",
        anchors: ["Channel Contribution Mix"],
      },
      {
        component_id: "TAB_HOME_CROSS_PRODUCT_ROAS",
        section: "cross-product-roas",
        anchors: ["Portfolio ROAS Comparison"],
        optional: true,
        missing_reason:
          "Conditional block not rendered when portfolio comparison has <2 products with positive spend.",
      },
    ],
  },
  {
    state_id: "sales-impact-light",
    tab: "sales-impact",
    nav_label: "Sales Impact",
    expected_text: "Annual Volume Impact",
    state: "light",
    components: [
      {
        component_id: "TAB_SALES_IMPACT_KPI_ROW",
        section: "kpi-row",
        anchors: ["Model R²", "Model R2", "Model Quality", "Total Spend"],
      },
      {
        component_id: "TAB_SALES_IMPACT_ANNUAL_CHART",
        section: "annual-volume-impact",
        anchors: ["Annual Volume Impact"],
      },
      {
        component_id: "TAB_SALES_IMPACT_CHANNEL_CONTRIBUTIONS",
        section: "channel-contributions",
        anchors: ["Channel Contributions"],
      },
      {
        component_id: "TAB_SALES_IMPACT_EXPORT_CONTROLS",
        section: "export-copy-controls",
        anchors: ["Export or copy raw rows for audit."],
      },
      {
        component_id: "TAB_SALES_IMPACT_NEXT_STEP_PROMPT",
        section: "next-step-prompt",
        anchors: ["Ready for the next step?"],
      },
    ],
  },
  {
    state_id: "response-curves-light-revenue",
    tab: "response-curves",
    nav_label: "Response Curves",
    expected_text: "Response Curves",
    state: "light-revenue",
    before_collect: "set_response_revenue",
    components: [
      {
        component_id: "TAB_RESPONSE_CURVES_CHANNEL_SELECT",
        section: "channel-select",
        anchors: ["Channel Select"],
      },
      {
        component_id: "TAB_RESPONSE_CURVES_MAIN_CHART_REVENUE",
        section: "main-curve-chart",
        anchors: ["Response Curves"],
      },
      {
        component_id: "TAB_RESPONSE_CURVES_CHANNEL_METRIC_CARDS",
        section: "channel-metric-cards",
        anchors: ["Current Spend"],
      },
    ],
  },
  {
    state_id: "response-curves-light-mroi",
    tab: "response-curves",
    nav_label: "Response Curves",
    expected_text: "Response Curves",
    state: "light-mroi",
    before_collect: "set_response_mroi",
    components: [
      {
        component_id: "TAB_RESPONSE_CURVES_MAIN_CHART_MROI",
        section: "mroi-view",
        anchors: ["Response Curves"],
      },
    ],
  },
  {
    state_id: "response-curves-light-saturation",
    tab: "response-curves",
    nav_label: "Response Curves",
    expected_text: "Response Curves",
    state: "light-saturation",
    before_collect: "set_response_saturation",
    components: [
      {
        component_id: "TAB_RESPONSE_CURVES_MAIN_CHART_SATURATION",
        section: "saturation-view",
        anchors: ["Response Curves"],
      },
    ],
  },
  {
    state_id: "budget-allocator-light-optimize",
    tab: "budget-allocator",
    nav_label: "Budget Allocator",
    expected_text: "Scenario Builder",
    state: "light-optimize",
    before_collect: "set_budget_optimize",
    components: [
      {
        component_id: "TAB_BUDGET_ALLOCATOR_SCENARIO_BUILDER_OPTIMIZE",
        section: "scenario-builder-optimize",
        anchors: ["Scenario Builder"],
      },
      {
        component_id: "TAB_BUDGET_ALLOCATOR_OPTIMIZATION_METRICS",
        section: "optimization-metrics-table",
        anchors: ["Optimization Metrics"],
      },
      {
        component_id: "TAB_BUDGET_ALLOCATOR_SCENARIO_RESULTS",
        section: "scenario-results-table",
        anchors: ["Scenario Results"],
      },
      {
        component_id: "TAB_BUDGET_ALLOCATOR_BUDGET_SPLIT",
        section: "budget-split-chart",
        anchors: ["Budget Split – Current vs Optimized", "Budget Split"],
      },
      {
        component_id: "TAB_BUDGET_ALLOCATOR_PLANNED_SCENARIO",
        section: "planned-scenario-panel",
        anchors: ["Planned Scenario"],
      },
    ],
  },
  {
    state_id: "budget-allocator-light-what-if",
    tab: "budget-allocator",
    nav_label: "Budget Allocator",
    expected_text: "Scenario Builder",
    state: "light-what-if",
    before_collect: "set_budget_what_if",
    components: [
      {
        component_id: "TAB_BUDGET_ALLOCATOR_SCENARIO_BUILDER_WHAT_IF",
        section: "scenario-builder-what-if",
        anchors: ["Scenario Builder"],
      },
    ],
  },
  {
    state_id: "experiment-light",
    tab: "experiment",
    nav_label: "Simulator",
    expected_text: "Channel Multipliers",
    state: "light",
    components: [
      {
        component_id: "TAB_SIMULATOR_HEADER_SAVED_SCENARIOS",
        section: "header-and-saved-scenarios",
        anchors: ["Saved Scenarios"],
      },
      {
        component_id: "TAB_SIMULATOR_CHANNEL_MULTIPLIERS",
        section: "channel-multipliers-panel",
        anchors: ["Channel Multipliers"],
      },
      {
        component_id: "TAB_SIMULATOR_REPRESENTATIVE_CURVE_CARD",
        section: "representative-channel-curve-card",
        anchors: ["Baseline"],
      },
      {
        component_id: "TAB_SIMULATOR_OPTIMIZATION_METRICS",
        section: "optimization-metrics-table",
        anchors: ["Optimization Metrics"],
      },
    ],
  },
  {
    state_id: "insights-light",
    tab: "insights",
    nav_label: "Insights",
    expected_text: "Channel Performance",
    state: "light",
    components: [
      {
        component_id: "TAB_INSIGHTS_HEADLINE_TRUST",
        section: "headline-and-trust-block",
        anchors: ["Channel Performance", "Your marketing is working."],
      },
      {
        component_id: "TAB_INSIGHTS_CHANNEL_PERFORMANCE_TABLE",
        section: "channel-performance-table",
        anchors: ["Channel Performance"],
      },
      {
        component_id: "TAB_INSIGHTS_RADAR_CHART",
        section: "radar-chart",
        anchors: ["Channel Efficiency Radar"],
      },
      {
        component_id: "TAB_INSIGHTS_EFFICIENCY_FRONTIER",
        section: "efficiency-frontier",
        anchors: ["Efficiency Frontier"],
      },
      {
        component_id: "TAB_INSIGHTS_ADSTOCK_BLOCK",
        section: "adstock-block",
        anchors: ["Adstock / Carryover Effects"],
      },
      {
        component_id: "TAB_INSIGHTS_RECOMMENDATIONS_ACTION",
        section: "recommendations-and-suggested-action",
        anchors: ["Suggested Action"],
      },
      {
        component_id: "TAB_INSIGHTS_DIAGNOSTICS",
        section: "diagnostics-block",
        anchors: ["Model Diagnostics"],
      },
    ],
  },
  {
    state_id: "settings-light",
    tab: "settings",
    nav_label: "System Flow & Settings",
    expected_text: "System Settings",
    state: "light",
    components: [
      {
        component_id: "TAB_SETTINGS_CONFIGURATION_SELECTION",
        section: "configuration-selection-panel",
        anchors: ["Configuration Selection"],
      },
      {
        component_id: "TAB_SETTINGS_CANDIDATE_PREVIEW",
        section: "candidate-preview-card",
        anchors: ["Candidate Preview"],
      },
      {
        component_id: "TAB_SETTINGS_ONE_PAGER_METRIC_CARDS",
        section: "one-pager-metric-cards",
        anchors: ["Model Accuracy (R²)", "Model Accuracy (R2)"],
      },
      {
        component_id: "TAB_SETTINGS_EFFICIENCY_CHART",
        section: "efficiency-chart",
        anchors: ["Share of Spend vs. Share of Effect"],
      },
      {
        component_id: "TAB_SETTINGS_DRIVER_CONTRIBUTION",
        section: "driver-contribution-chart",
        anchors: ["Driver Contribution"],
      },
      {
        component_id: "TAB_SETTINGS_MODEL_ANALYSIS",
        section: "model-analysis-table",
        anchors: ["Model Analysis & Verification"],
        optional: true,
        missing_reason:
          "Conditional model-analysis block is hidden when card_analysis payload is unavailable.",
      },
    ],
  },
  {
    state_id: "geography-light-advanced",
    tab: "geography",
    nav_label: "Geography",
    expected_text: "Territory Analysis",
    state: "light-advanced",
    before_collect: "set_geography_advanced",
    components: [
      {
        component_id: "TAB_GEOGRAPHY_ADVANCED_MAP",
        section: "advanced-map-view",
        anchors: ["Territory Map"],
      },
      {
        component_id: "TAB_GEOGRAPHY_TERRITORY_TABLE",
        section: "territory-detail-table",
        anchors: ["Territory Detail"],
      },
      {
        component_id: "TAB_GEOGRAPHY_CHANNEL_DISPERSION",
        section: "channel-dispersion-cards",
        anchors: ["Channel Dispersion Across Territories"],
      },
      {
        component_id: "TAB_GEOGRAPHY_PRODUCT_COMPARISON",
        section: "product-comparison-table",
        anchors: ["Product Comparison"],
      },
    ],
  },
  {
    state_id: "geography-light-basic",
    tab: "geography",
    nav_label: "Geography",
    expected_text: "Advanced Tier Required",
    state: "light-basic",
    before_collect: "set_geography_basic",
    components: [
      {
        component_id: "TAB_GEOGRAPHY_BASIC_LOCKED_PLACEHOLDER",
        section: "basic-tier-locked-placeholder",
        anchors: ["Advanced Tier Required"],
      },
    ],
  },
  {
    state_id: "home-dark",
    tab: "home",
    nav_label: "Home",
    expected_text: "Dashboard Overview",
    state: "dark",
    before_collect: "set_dark_theme",
    components: [
      {
        component_id: "TAB_HOME_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["Dashboard Overview"],
      },
    ],
  },
  {
    state_id: "sales-impact-dark",
    tab: "sales-impact",
    nav_label: "Sales Impact",
    expected_text: "Annual Volume Impact",
    state: "dark",
    before_collect: "set_dark_theme",
    components: [
      {
        component_id: "TAB_SALES_IMPACT_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["Annual Volume Impact"],
      },
    ],
  },
  {
    state_id: "response-curves-dark",
    tab: "response-curves",
    nav_label: "Response Curves",
    expected_text: "Response Curves",
    state: "dark",
    before_collect: "set_dark_theme_response_revenue",
    components: [
      {
        component_id: "TAB_RESPONSE_CURVES_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["Response Curves"],
      },
    ],
  },
  {
    state_id: "budget-allocator-dark",
    tab: "budget-allocator",
    nav_label: "Budget Allocator",
    expected_text: "Scenario Builder",
    state: "dark",
    before_collect: "set_dark_theme_budget_optimize",
    components: [
      {
        component_id: "TAB_BUDGET_ALLOCATOR_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["Scenario Builder"],
      },
    ],
  },
  {
    state_id: "experiment-dark",
    tab: "experiment",
    nav_label: "Simulator",
    expected_text: "Channel Multipliers",
    state: "dark",
    before_collect: "set_dark_theme",
    components: [
      {
        component_id: "TAB_SIMULATOR_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["Channel Multipliers"],
      },
    ],
  },
  {
    state_id: "insights-dark",
    tab: "insights",
    nav_label: "Insights",
    expected_text: "Channel Performance",
    state: "dark",
    before_collect: "set_dark_theme",
    components: [
      {
        component_id: "TAB_INSIGHTS_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["Channel Performance"],
      },
    ],
  },
  {
    state_id: "settings-dark",
    tab: "settings",
    nav_label: "System Flow & Settings",
    expected_text: "System Settings",
    state: "dark",
    before_collect: "set_dark_theme",
    components: [
      {
        component_id: "TAB_SETTINGS_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["System Settings"],
      },
    ],
  },
  {
    state_id: "geography-dark",
    tab: "geography",
    nav_label: "Geography",
    expected_text: "Territory Analysis",
    state: "dark",
    before_collect: "set_dark_theme_geography_advanced",
    components: [
      {
        component_id: "TAB_GEOGRAPHY_DARK_OVERVIEW",
        section: "tab-overview",
        anchors: ["Territory Analysis"],
      },
    ],
  },
];

const DEFAULT_ACTIONS = {
  set_response_revenue: [
    { type: "click_text", selector: "button", text: "Revenue", wait_ms: 500 },
  ],
  set_response_mroi: [
    { type: "click_text", selector: "button", text: "mROI", wait_ms: 600 },
  ],
  set_response_saturation: [
    { type: "click_text", selector: "button", text: "Saturation %", wait_ms: 600 },
  ],
  set_budget_optimize: [
    { type: "click_text", selector: "button", text: "Optimize", wait_ms: 600 },
  ],
  set_budget_what_if: [
    { type: "click_text", selector: "button", text: "What-If", wait_ms: 700 },
  ],
  set_geography_advanced: [
    {
      type: "goto_tab",
      nav_label: "System Flow & Settings",
      tab: "settings",
      expected_text: "System Settings",
    },
    { type: "click_text", selector: "button", text: "Advanced", wait_ms: 700 },
    {
      type: "goto_tab",
      nav_label: "Geography",
      tab: "geography",
      expected_text: "Territory Analysis",
    },
  ],
  set_geography_basic: [
    {
      type: "goto_tab",
      nav_label: "System Flow & Settings",
      tab: "settings",
      expected_text: "System Settings",
    },
    { type: "click_text", selector: "button", text: "Basic", wait_ms: 700 },
    {
      type: "goto_tab",
      nav_label: "Geography",
      tab: "geography",
      expected_text: "Advanced Tier Required",
    },
  ],
  set_dark_theme: [{ type: "set_theme", theme: "dark", wait_ms: 500 }],
  set_dark_theme_response_revenue: [
    { type: "set_theme", theme: "dark" },
    { type: "click_text", selector: "button", text: "Revenue", wait_ms: 600 },
  ],
  set_dark_theme_budget_optimize: [
    { type: "set_theme", theme: "dark" },
    { type: "click_text", selector: "button", text: "Optimize", wait_ms: 600 },
  ],
  set_dark_theme_geography_advanced: [
    { type: "set_theme", theme: "dark" },
    {
      type: "goto_tab",
      nav_label: "System Flow & Settings",
      tab: "settings",
      expected_text: "System Settings",
    },
    { type: "click_text", selector: "button", text: "Advanced", wait_ms: 700 },
    {
      type: "goto_tab",
      nav_label: "Geography",
      tab: "geography",
      expected_text: "Territory Analysis",
    },
  ],
};

const DEFAULT_SPEC = {
  navigation: {
    tab_button_selector: "div.w-64 button",
    enable_fallback_url: true,
    fallback_url_template: "{dashboard_url}/?tab={tab}&{canonical_query}",
    fallback_wait_until: "networkidle",
  },
  tab_meta: DEFAULT_TAB_META,
  states: DEFAULT_STATES,
  actions: DEFAULT_ACTIONS,
};

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function ensureArray(value) {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

function formatTemplate(template, vars) {
  if (!template) return "";
  return String(template).replace(/\{([a-zA-Z0-9_]+)\}/g, (_, key) =>
    Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : ""
  );
}

function mergeTabMeta(base = {}, override = {}) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(override || {})) {
    merged[key] = { ...(base[key] || {}), ...(value || {}) };
  }
  return merged;
}

function normalizeStates(states) {
  if (!Array.isArray(states) || states.length === 0) {
    throw new Error("Capture spec must provide a non-empty states array.");
  }
  return states.map((state, idx) => {
    if (!state || typeof state !== "object") {
      throw new Error(`Invalid state at index ${idx}: expected object.`);
    }
    if (!state.state_id || !state.tab || !state.state) {
      throw new Error(
        `Invalid state at index ${idx}: state_id, tab, and state are required.`
      );
    }
    const components = ensureArray(state.components).map((component, compIdx) => {
      if (!component || typeof component !== "object") {
        throw new Error(
          `Invalid component in state ${state.state_id} at index ${compIdx}: expected object.`
        );
      }
      if (!component.component_id || !component.section) {
        throw new Error(
          `Invalid component in state ${state.state_id}: component_id and section are required.`
        );
      }
      return {
        ...component,
        anchors: ensureArray(component.anchors),
        selectors: ensureArray(component.selectors || component.selector),
      };
    });
    return {
      ...state,
      components,
    };
  });
}

function resolveActionList(actionOrAlias, actionMap, stack = []) {
  if (actionOrAlias == null) return [];
  if (typeof actionOrAlias === "string") {
    if (stack.includes(actionOrAlias)) {
      throw new Error(`Cycle detected while resolving action alias "${actionOrAlias}".`);
    }
    const mapped = actionMap[actionOrAlias];
    if (mapped == null) {
      throw new Error(`Unknown action alias "${actionOrAlias}" in capture spec.`);
    }
    return resolveActionList(mapped, actionMap, [...stack, actionOrAlias]);
  }
  if (Array.isArray(actionOrAlias)) {
    return actionOrAlias.flatMap((item) => resolveActionList(item, actionMap, stack));
  }
  if (typeof actionOrAlias === "object") {
    return [actionOrAlias];
  }
  throw new Error(`Unsupported action type: ${typeof actionOrAlias}`);
}

function loadCaptureSpec() {
  const usingExplicitSpecPath = Boolean(CAPTURE_SPEC_FROM_ENV);
  let parsed = null;
  let specSource = "built-in defaults";

  if (fs.existsSync(CAPTURE_SPEC_PATH)) {
    const raw = fs.readFileSync(CAPTURE_SPEC_PATH, "utf8");
    parsed = JSON.parse(raw);
    specSource = CAPTURE_SPEC_PATH;
  } else if (usingExplicitSpecPath) {
    throw new Error(`CAPTURE_SPEC_PATH was provided but file was not found: ${CAPTURE_SPEC_PATH}`);
  } else {
    console.log(
      `[info] capture spec not found at ${CAPTURE_SPEC_PATH}; using built-in default spec`
    );
  }

  const defaults = deepClone(DEFAULT_SPEC);
  if (!parsed) {
    return {
      spec: {
        ...defaults,
        states: normalizeStates(defaults.states),
      },
      source: specSource,
    };
  }

  const merged = {
    ...defaults,
    ...parsed,
    navigation: {
      ...defaults.navigation,
      ...(parsed.navigation || {}),
    },
    tab_meta: mergeTabMeta(defaults.tab_meta, parsed.tab_meta || {}),
    actions: {
      ...defaults.actions,
      ...(parsed.actions || {}),
    },
    states: normalizeStates(parsed.states || defaults.states),
  };

  return {
    spec: merged,
    source: specSource,
  };
}

function slug(s) {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s/_-]/g, "")
    .replace(/[\s/_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

async function waitForHttp(url, timeoutMs = 60000) {
  const start = Date.now();
  let lastErr = "";
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
      lastErr = `status=${res.status}`;
    } catch (err) {
      lastErr = String(err);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Service not ready: ${url}. Last error: ${lastErr}`);
}

async function waitForText(page, text, timeout = 45000) {
  await page.waitForFunction(
    (needle) => {
      const body = document.body?.innerText || "";
      return body.toLowerCase().includes(String(needle).toLowerCase());
    },
    text,
    { timeout }
  );
}

async function clickByText(page, selector, text, exact = false) {
  return page.evaluate(
    ({ selector, text, exact }) => {
      const target = String(text || "").trim().toLowerCase();
      const els = Array.from(document.querySelectorAll(selector));
      for (const el of els) {
        if (!el || el.disabled) continue;
        const value = (el.innerText || el.textContent || "").trim().toLowerCase();
        if ((exact && value === target) || (!exact && value.includes(target))) {
          el.click();
          return true;
        }
      }
      return false;
    },
    { selector, text, exact }
  );
}

async function clickBySelector(page, selector, index = 0) {
  return page.evaluate(
    ({ selector, index }) => {
      const nodes = Array.from(document.querySelectorAll(selector));
      const node = nodes[index] || null;
      if (!node || node.disabled) return false;
      node.click();
      return true;
    },
    { selector, index }
  );
}

async function scrollToText(page, text) {
  await page.evaluate((needle) => {
    const target = String(needle || "").trim().toLowerCase();
    const nodes = Array.from(
      document.querySelectorAll("h1,h2,h3,h4,h5,p,span,th,td,label,button,div")
    );
    for (const n of nodes) {
      if (!n || n.offsetParent === null) continue;
      const value = (n.innerText || n.textContent || "").trim().toLowerCase();
      if (value.includes(target)) {
        n.scrollIntoView({ block: "center", inline: "nearest" });
        return;
      }
    }
    window.scrollTo(0, 0);
  }, text);
  await page.waitForTimeout(350);
}

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem("theme", t);
    document.documentElement.classList.remove("light", "dark");
    document.documentElement.classList.add(t);
  }, theme);
  await page.waitForTimeout(450);
}

async function gotoTab(page, label, tabKey, expectedText, navigation, urlTokens) {
  const nav = navigation || DEFAULT_SPEC.navigation;
  const tabButtonSelector = nav.tab_button_selector || "div.w-64 button";
  const enableFallback = nav.enable_fallback_url !== false;
  const fallbackTemplate =
    nav.fallback_url_template || "{dashboard_url}/?tab={tab}&{canonical_query}";
  const fallbackWaitUntil = nav.fallback_wait_until || "networkidle";

  let reached = false;
  if (label) {
    const clicked = await clickByText(page, tabButtonSelector, label, false);
    if (clicked && expectedText) {
      try {
        await waitForText(page, expectedText, 10000);
        reached = true;
      } catch {
        reached = false;
      }
    } else if (clicked) {
      reached = true;
    }
  }

  if (!reached && enableFallback && tabKey) {
    const fallbackUrl = formatTemplate(fallbackTemplate, {
      ...(urlTokens || {}),
      tab: tabKey,
      tab_key: tabKey,
      nav_label: label || "",
    });
    await page.goto(fallbackUrl, {
      waitUntil: fallbackWaitUntil,
    });
    if (expectedText) {
      try {
        await waitForText(page, expectedText, 20000);
      } catch {
        console.warn(
          `[warn] expected text not found after navigation: tab=${tabKey}, expected="${expectedText}"`
        );
      }
    }
  }
  await page.waitForTimeout(500);
}

async function getPageDimensions(page) {
  return page.evaluate(() => {
    const b = document.body;
    const d = document.documentElement;
    const width = Math.max(
      b?.scrollWidth || 0,
      b?.offsetWidth || 0,
      d?.clientWidth || 0,
      d?.scrollWidth || 0,
      d?.offsetWidth || 0
    );
    const height = Math.max(
      b?.scrollHeight || 0,
      b?.offsetHeight || 0,
      d?.clientHeight || 0,
      d?.scrollHeight || 0,
      d?.offsetHeight || 0
    );
    return { width, height };
  });
}

async function locateBoxByText(page, anchorText, section = "") {
  await scrollToText(page, anchorText);
  return page.evaluate(({ needle, sectionName }) => {
    const target = String(needle || "").trim().toLowerCase();
    const section = String(sectionName || "").trim().toLowerCase();
    const allowLargeContainer = section === "tab-overview";
    const nodes = Array.from(
      document.querySelectorAll("h1,h2,h3,h4,h5,p,span,th,td,label,button,div")
    );

    function visible(el) {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      if (rect.width < 6 || rect.height < 6) return false;
      if (rect.bottom < 0 || rect.right < 0) return false;
      if (rect.top > window.innerHeight || rect.left > window.innerWidth) return false;
      const style = window.getComputedStyle(el);
      return style.visibility !== "hidden" && style.display !== "none";
    }

    function score(el, text) {
      const t = (text || "").toLowerCase();
      let s = 0;
      if (t === target) s += 95;
      else if (t.startsWith(target)) s += 55;
      else if (t.includes(target)) s += 30;

      s -= Math.min(Math.abs(t.length - target.length) * 0.4, 45);
      const tag = (el.tagName || "").toLowerCase();
      if (["h1", "h2", "h3", "h4", "h5", "th", "label", "button"].includes(tag)) {
        s += 10;
      }
      if (tag === "div") s -= 6;

      if (t.length > 180) s -= 30;
      else if (t.length > 120) s -= 15;

      const rect = el.getBoundingClientRect();
      const area = rect.width * rect.height;
      const viewportArea = window.innerWidth * window.innerHeight;
      if (area > 400 && area < viewportArea * 0.35) s += 10;
      if (area > viewportArea * 0.52) s -= 50;
      return s;
    }

    const candidates = [];
    for (const el of nodes) {
      if (!visible(el)) continue;
      const text = (el.innerText || el.textContent || "").trim();
      if (!text) continue;
      const tag = (el.tagName || "").toLowerCase();
      if (tag === "div" && text.length > 220) continue;
      if (text.length > 360) continue;
      if (!text.toLowerCase().includes(target)) continue;
      candidates.push({ el, text, score: score(el, text) });
    }

    if (candidates.length === 0) return null;
    candidates.sort((a, b) => b.score - a.score);

    let chosen = candidates[0].el;
    let chosenRect = chosen.getBoundingClientRect();

    // Expand to nearest meaningful card/chart container, but cap size to avoid page-level boxes.
    let parent = chosen.parentElement;
    for (let i = 0; i < 8 && parent; i += 1) {
      const tag = (parent.tagName || "").toLowerCase();
      if (tag === "body" || tag === "html") break;
      const rect = parent.getBoundingClientRect();
      const cls = (parent.className || "").toString().toLowerCase();
      const parentText = (parent.innerText || parent.textContent || "").trim();
      const isContainerLike =
        (typeof parent.matches === "function" &&
          parent.matches(
            "[data-slot='card'], .card, table, [role='table'], .recharts-wrapper, .recharts-responsive-container, .rounded-2xl, .rounded-xl, .rounded-lg"
          )) ||
        cls.includes("card") ||
        cls.includes("rounded") ||
        cls.includes("panel") ||
        cls.includes("section") ||
        cls.includes("chart");

      const areaRatio = (rect.width * rect.height) / (window.innerWidth * window.innerHeight);
      const maxAreaRatio = allowLargeContainer ? 0.82 : 0.42;
      const maxWidthRatio = allowLargeContainer ? 0.96 : 0.90;
      const maxHeightRatio = allowLargeContainer ? 0.94 : 0.68;
      const reasonableSize =
        rect.width > chosenRect.width * 1.02 &&
        rect.height > chosenRect.height * 1.02 &&
        rect.width <= window.innerWidth * maxWidthRatio &&
        rect.height <= window.innerHeight * maxHeightRatio &&
        areaRatio <= maxAreaRatio &&
        parentText.length < 900;

      if (isContainerLike && reasonableSize) {
        chosen = parent;
        chosenRect = rect;
      }
      parent = parent.parentElement;
    }

    const padX = Math.max(8, Math.round(chosenRect.width * 0.01));
    const padY = Math.max(8, Math.round(chosenRect.height * 0.02));

    const x = Math.max(0, chosenRect.left + window.scrollX - padX);
    const y = Math.max(0, chosenRect.top + window.scrollY - padY);
    const docW = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
    const docH = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0);
    const width = Math.max(24, Math.min(chosenRect.width + padX * 2, docW - x - 2));
    const height = Math.max(24, Math.min(chosenRect.height + padY * 2, docH - y - 2));

    return {
      x,
      y,
      width,
      height,
      matched_text: (chosen.innerText || "").trim().slice(0, 160),
      anchor: needle,
    };
  }, { needle: anchorText, sectionName: section });
}

async function locateBoxBySelector(page, selector) {
  return page.evaluate((cssSelector) => {
    const node = document.querySelector(cssSelector);
    if (!node) return null;
    const rect = node.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return null;

    const style = window.getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return null;

    const padX = Math.max(6, Math.round(rect.width * 0.01));
    const padY = Math.max(6, Math.round(rect.height * 0.02));
    const x = Math.max(0, rect.left + window.scrollX - padX);
    const y = Math.max(0, rect.top + window.scrollY - padY);
    const docW = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
    const docH = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0);
    const width = Math.max(18, Math.min(rect.width + padX * 2, docW - x - 2));
    const height = Math.max(18, Math.min(rect.height + padY * 2, docH - y - 2));
    return {
      x,
      y,
      width,
      height,
      matched_text: (node.innerText || node.textContent || "").trim().slice(0, 160),
      anchor: `selector:${cssSelector}`,
    };
  }, selector);
}

async function findBoxWithSelectors(page, selectors = []) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    for (const selector of selectors) {
      if (!selector) continue;
      const box = await locateBoxBySelector(page, selector);
      if (box) return { ...box, anchor_text: `selector:${selector}` };
    }
    await page.waitForTimeout(350);
  }
  return null;
}

async function findBoxWithAnchors(page, anchors = [], section) {
  for (let attempt = 0; attempt < 14; attempt += 1) {
    for (const anchor of anchors) {
      const box = await locateBoxByText(page, anchor, section);
      if (box) return { ...box, anchor_text: anchor };
    }
    await page.waitForTimeout(500);
  }
  return null;
}

async function findBoxForComponent(page, component) {
  if (component && component.bbox && typeof component.bbox === "object") {
    const raw = component.bbox;
    const x = Number(raw.x ?? raw.left ?? 0);
    const y = Number(raw.y ?? raw.top ?? 0);
    const width = Number(raw.width ?? raw.w ?? 0);
    const height = Number(raw.height ?? raw.h ?? 0);
    if (width > 0 && height > 0) {
      return {
        x,
        y,
        width,
        height,
        matched_text: "bbox-from-spec",
        anchor_text: "bbox",
      };
    }
  }

  const selectorBox = await findBoxWithSelectors(page, component?.selectors || []);
  if (selectorBox) return selectorBox;
  return findBoxWithAnchors(page, component?.anchors || [], component?.section || "");
}

async function executeAction(page, action, runtime) {
  if (!action || typeof action !== "object") return;
  const type = String(action.type || "").trim().toLowerCase();
  if (!type) {
    throw new Error(`Action is missing required field "type": ${JSON.stringify(action)}`);
  }

  if (type === "click_text") {
    const selector = action.selector || "button";
    const text = action.text || action.label;
    if (!text) throw new Error("click_text action requires text or label.");
    const clicked = await clickByText(page, selector, text, Boolean(action.exact));
    if (!clicked && action.required !== false) {
      throw new Error(`click_text failed: selector="${selector}" text="${text}"`);
    }
  } else if (type === "click_selector") {
    if (!action.selector) throw new Error("click_selector action requires selector.");
    const clicked = await clickBySelector(page, action.selector, Number(action.index || 0));
    if (!clicked && action.required !== false) {
      throw new Error(`click_selector failed: selector="${action.selector}"`);
    }
  } else if (type === "goto_tab") {
    await gotoTab(
      page,
      action.nav_label || action.label,
      action.tab || action.tab_key,
      action.expected_text || "",
      runtime.navigation,
      runtime.urlTokens
    );
  } else if (type === "goto_url") {
    const url =
      action.url ||
      formatTemplate(action.url_template || "", {
        ...(runtime.urlTokens || {}),
        tab: action.tab || "",
      });
    if (!url) throw new Error("goto_url action requires url or url_template.");
    await page.goto(url, { waitUntil: action.wait_until || "networkidle" });
    if (action.expected_text) {
      await waitForText(page, action.expected_text, Number(action.timeout_ms || 25000));
    }
  } else if (type === "set_theme") {
    await setTheme(page, action.theme || "light");
  } else if (type === "wait_text") {
    if (!action.text) throw new Error("wait_text action requires text.");
    await waitForText(page, action.text, Number(action.timeout_ms || 45000));
  } else if (type === "wait_ms") {
    await page.waitForTimeout(Number(action.ms || action.wait_ms || 300));
  } else if (type === "scroll_text") {
    if (!action.text) throw new Error("scroll_text action requires text.");
    await scrollToText(page, action.text);
  } else if (type === "press_key") {
    if (!action.key) throw new Error("press_key action requires key.");
    await page.keyboard.press(String(action.key));
  } else {
    throw new Error(`Unsupported action type "${type}"`);
  }

  if (action.wait_text) {
    await waitForText(page, action.wait_text, Number(action.timeout_ms || 25000));
  }
  if (action.wait_ms && type !== "wait_ms") {
    await page.waitForTimeout(Number(action.wait_ms));
  }
}

async function runBeforeCollect(page, actionOrAlias, runtime) {
  const actions = resolveActionList(actionOrAlias, runtime.actions);
  for (const action of actions) {
    await executeAction(page, action, runtime);
  }
}

async function main() {
  fs.mkdirSync(CLEAN_DIR, { recursive: true });
  fs.mkdirSync(path.dirname(MANIFEST_PATH), { recursive: true });

  await waitForHttp(DASHBOARD_URL);
  await waitForHttp(API_HEALTH_URL);
  const { spec: captureSpec, source: captureSpecSource } = loadCaptureSpec();
  const tabMetaByTab = captureSpec.tab_meta || {};
  const captureStates = captureSpec.states || [];
  const runtime = {
    navigation: captureSpec.navigation || DEFAULT_SPEC.navigation,
    actions: captureSpec.actions || DEFAULT_ACTIONS,
    urlTokens: {
      dashboard_url: DASHBOARD_URL,
      api_health_url: API_HEALTH_URL,
      country: COUNTRY,
      product: PRODUCT,
      year: String(YEAR),
      version: VERSION,
      data_source: DATA_SOURCE,
      canonical_query: CANONICAL_QUERY,
    },
  };
  console.log(`[info] capture spec source: ${captureSpecSource}`);
  console.log(`[info] capture states: ${captureStates.length}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1680, height: 1080 } });
  const page = await context.newPage();

  const states = [];
  const captures = [];
  const omittedComponents = [];
  let hotspotCounter = 1;

  try {
    const initialUrl = formatTemplate(
      captureSpec.initial_url_template || "{dashboard_url}/?tab=home&{canonical_query}",
      runtime.urlTokens
    );
    await page.goto(initialUrl, {
      waitUntil: captureSpec.initial_wait_until || "networkidle",
    });
    if (captureSpec.initial_wait_text) {
      await waitForText(page, captureSpec.initial_wait_text, Number(captureSpec.initial_wait_timeout_ms || 45000));
    } else {
      await waitForText(page, "Dashboard Overview");
    }
    await setTheme(page, captureSpec.initial_theme || "light");
    await runBeforeCollect(page, captureSpec.initial_actions, runtime);

    for (let idx = 0; idx < captureStates.length; idx += 1) {
      const st = captureStates[idx];
      console.log(`[state:start] ${st.state_id}`);

      await gotoTab(page, st.nav_label, st.tab, st.expected_text, runtime.navigation, runtime.urlTokens);
      await runBeforeCollect(page, st.before_collect, runtime);
      if (st.expected_text) {
        try {
          await waitForText(page, st.expected_text, 25000);
        } catch {
          console.warn(
            `[warn] expected text not present before capture: state=${st.state_id}, expected="${st.expected_text}"`
          );
        }
      }
      await page.waitForTimeout(800);

      const dims = await getPageDimensions(page);
      const screenshotName = `${String(idx + 1).padStart(3, "0")}-${slug(st.tab)}-${slug(
        st.state
      )}-map.png`;
      const screenshotPath = path.join(CLEAN_DIR, screenshotName);

      const stateHotspots = [];

      for (const comp of st.components) {
        const box = await findBoxForComponent(page, comp);
        if (!box) {
          if (comp.optional) {
            omittedComponents.push({
              state_id: st.state_id,
              tab: st.tab,
              state: st.state,
              component_id: comp.component_id,
              section: comp.section,
              anchors: comp.anchors || [],
              reason: comp.missing_reason || "Optional component was not rendered in DOM.",
            });
            continue;
          }
          throw new Error(
            `Hotspot bbox not found for component ${comp.component_id} in state ${st.state_id}`
          );
        }

        const clamped = {
          x: Math.max(0, Math.min(box.x, dims.width - 2)),
          y: Math.max(0, Math.min(box.y, dims.height - 2)),
          width: Math.max(8, Math.min(box.width, dims.width - box.x)),
          height: Math.max(8, Math.min(box.height, dims.height - box.y)),
        };

        const bbox_pct = {
          x: Number(((clamped.x / dims.width) * 100).toFixed(6)),
          y: Number(((clamped.y / dims.height) * 100).toFixed(6)),
          width: Number(((clamped.width / dims.width) * 100).toFixed(6)),
          height: Number(((clamped.height / dims.height) * 100).toFixed(6)),
        };

        const tabMeta =
          (st.state === "dark" ? tabMetaByTab.dark : tabMetaByTab[st.tab]) ||
          tabMetaByTab[st.tab] ||
          tabMetaByTab.default ||
          {};
        const hotspot_id = `HS_${String(hotspotCounter).padStart(3, "0")}`;
        hotspotCounter += 1;

        const entry = {
          hotspot_id,
          state_id: st.state_id,
          component_id: comp.component_id,
          tab: st.tab,
          state: st.state,
          section: comp.section,
          anchor_text: box.anchor_text,
          matched_text: box.matched_text,
          screenshot: screenshotPath,
          bbox: clamped,
          bbox_pct,
          source_file: tabMeta.source_file || "",
          ui_role: tabMeta.ui_role || "",
          business_meaning: tabMeta.business_meaning || "",
          interactions: tabMeta.interactions || "",
          api_endpoints: ensureArray(tabMeta.api_endpoints),
          upstream_artifacts: ensureArray(tabMeta.upstream_artifacts),
          fallback_behavior: tabMeta.fallback_behavior || "",
        };

        stateHotspots.push(hotspot_id);
        captures.push(entry);
      }

      await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: "instant" }));
      await page.waitForTimeout(350);
      await page.screenshot({ path: screenshotPath, fullPage: true });

      states.push({
        state_id: st.state_id,
        tab: st.tab,
        state: st.state,
        nav_label: st.nav_label,
        expected_text: st.expected_text,
        screenshot: screenshotPath,
        full_width: dims.width,
        full_height: dims.height,
        hotspot_ids: stateHotspots,
        omitted_components: omittedComponents
          .filter((m) => m.state_id === st.state_id)
          .map((m) => m.component_id),
      });

      // Reset to light after dark pass to avoid accidental carry-over.
      if (st.state === "dark") {
        await setTheme(page, "light");
      }

      console.log(`[state:done] ${st.state_id} -> ${screenshotPath}`);
    }

    const manifest = {
      generated_at: new Date().toISOString(),
      canonical_context: {
        country: COUNTRY,
        product: PRODUCT,
        year: YEAR,
        version: VERSION,
        data_source: DATA_SOURCE,
      },
      capture_spec: {
        source: captureSpecSource,
        path: CAPTURE_SPEC_PATH,
        using_default_spec: captureSpecSource === "built-in defaults",
        state_count: captureStates.length,
      },
      screenshot_count: states.length,
      component_count: captures.length,
      omitted_component_count: omittedComponents.length,
      states,
      captures,
      omitted_components: omittedComponents,
    };

    fs.writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2));
    console.log(`Captured ${states.length} state screenshots into ${CLEAN_DIR}`);
    console.log(`Captured ${captures.length} hotspots with DOM bounding boxes`);
    if (omittedComponents.length > 0) {
      console.log(
        `Omitted ${omittedComponents.length} conditional components without DOM presence`
      );
    }
    console.log(`Manifest: ${MANIFEST_PATH}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
