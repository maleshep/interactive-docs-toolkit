#!/usr/bin/env python3
"""Build business-first dashboard documentation artifacts from capture manifest.

Outputs (all under temp run dir):
- spec/callouts.json
- manifests/callout_manifest.json
- manifests/business_semantics.json
- docs/DASHBOARD_BUSINESS_REFERENCE.md
- docs/DASHBOARD_BUSINESS_REFERENCE.html
- manifests/qa_report.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Pillow is required to generate annotated screenshots. "
        "Install in the current venv: pip install pillow"
    ) from exc


TAB_ORDER = [
    "home",
    "sales-impact",
    "response-curves",
    "budget-allocator",
    "experiment",
    "insights",
    "settings",
    "geography",
]

TAB_TITLE = {
    "home": "Home",
    "sales-impact": "Sales Impact",
    "response-curves": "Response Curves",
    "budget-allocator": "Budget Allocator",
    "experiment": "Simulator",
    "insights": "Insights",
    "settings": "Settings",
    "geography": "Geography",
}

TAB_PURPOSE = {
    "home": "Orient business users on current spend, return, and where to investigate next.",
    "sales-impact": "Validate model credibility and understand which channels are truly moving sales.",
    "response-curves": "Evaluate diminishing returns and decide where incremental budget still has headroom.",
    "budget-allocator": "Turn strategy constraints into a recommended allocation and compare business impact.",
    "experiment": "Stress-test plan assumptions with manual multipliers before committing spend changes.",
    "insights": "Translate model outputs into recommendations, risks, and confidence for decision meetings.",
    "settings": "Control the active model context and verify model quality before operational decisions.",
    "geography": "Identify territorial heterogeneity so deployment can be tailored by region and tier.",
}

TAB_DECISIONS = {
    "home": "Decide where to start analysis and whether immediate budget optimization is warranted.",
    "sales-impact": "Decide whether the decomposition is credible enough to support budget shifts.",
    "response-curves": "Decide which channels can absorb more spend and which are close to saturation.",
    "budget-allocator": "Decide the target allocation scenario to export, share, or move into simulation.",
    "experiment": "Decide whether a proposed reallocation is robust under manual what-if assumptions.",
    "insights": "Decide executive actions while balancing upside, uncertainty, and diagnostic risk.",
    "settings": "Decide which model version/tier is fit-for-purpose before cross-team communication.",
    "geography": "Decide where to localize channel strategy and where a national rule is sufficient.",
}

REQUIRED_SECTIONS = {
    "home": {
        "tab-overview",
        "kpi-row",
        "quick-actions-and-scenarios",
        "monthly-trend",
        "channel-mix",
        "cross-product-roas",
    },
    "sales-impact": {
        "kpi-row",
        "annual-volume-impact",
        "channel-contributions",
        "export-copy-controls",
        "next-step-prompt",
    },
    "response-curves": {
        "channel-select",
        "main-curve-chart",
        "mroi-view",
        "saturation-view",
        "channel-metric-cards",
    },
    "budget-allocator": {
        "scenario-builder-optimize",
        "scenario-builder-what-if",
        "optimization-metrics-table",
        "scenario-results-table",
        "budget-split-chart",
        "planned-scenario-panel",
    },
    "experiment": {
        "header-and-saved-scenarios",
        "channel-multipliers-panel",
        "representative-channel-curve-card",
        "optimization-metrics-table",
    },
    "insights": {
        "headline-and-trust-block",
        "channel-performance-table",
        "radar-chart",
        "efficiency-frontier",
        "adstock-block",
        "recommendations-and-suggested-action",
        "diagnostics-block",
    },
    "geography": {
        "advanced-map-view",
        "territory-detail-table",
        "channel-dispersion-cards",
        "product-comparison-table",
        "basic-tier-locked-placeholder",
    },
    "settings": {
        "configuration-selection-panel",
        "candidate-preview-card",
        "one-pager-metric-cards",
        "efficiency-chart",
        "driver-contribution-chart",
        "model-analysis-table",
    },
}

SECTION_TEMPLATE: dict[str, dict[str, Any]] = {
    "tab-overview": {
        "title": "Tab Orientation",
        "business_question": "What is this tab for, and which decision should I make here?",
        "kpi_name": "Navigation Context",
        "bbox": [90, 120, 1420, 180],
        "kpi_or_chart_definition": "Landing context for the tab, including headline and action orientation.",
        "formula": "No arithmetic KPI. This section is contextual and directional.",
        "inputs": ["selected country", "selected product", "selected year", "selected version", "selected tier"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: context and selected scope are clearly aligned. Risk: users act on wrong product/year context.",
        "decision_supported": "Should I continue analysis in this tab or switch to another module?",
        "recommended_next_action": "Verify selected context, then use the main KPI/graph below for decisioning.",
        "misinterpretation_risks": "Treating overview text as evidence rather than using quantitative sections.",
        "data_freshness_or_caveats": "Depends on selected model version and available artifacts.",
    },
    "kpi-row": {
        "title": "KPI Cards",
        "business_question": "Are we spending efficiently and creating enough incremental sales?",
        "kpi_name": "Topline KPIs",
        "bbox": [120, 210, 1420, 220],
        "kpi_or_chart_definition": "Topline scorecards summarizing spend, incremental sales, efficiency, and model quality.",
        "formula": "Total Spend = Σ Spend_i; Incremental Sales = Σ Incremental_i; ROI = Incremental Sales / Total Spend; R² = 1 - SSE/SST.",
        "inputs": ["contribution rows (Spend, Incremental)", "model statistics (R²)", "channel-level decomposition"],
        "unit_and_scale": "Currency and ratio (x), plus unitless R² [0..1].",
        "how_to_read_good_vs_risk": "Good: ROI improving with stable/strong R². Risk: high ROI but weak model quality or unstable decomposition.",
        "decision_supported": "Should leadership trust this plan enough to move budget now?",
        "recommended_next_action": "If KPI signal is mixed, inspect Sales Impact and Insights before reallocating.",
        "misinterpretation_risks": "Comparing KPI values across different products/currencies without normalization.",
        "data_freshness_or_caveats": "Sensitive to selected year/version and may shift with new model runs.",
    },
    "quick-actions-and-scenarios": {
        "title": "Quick Actions",
        "business_question": "Which module should I open next to answer the current planning question?",
        "kpi_name": "Workflow Shortcuts",
        "bbox": [90, 450, 1450, 270],
        "kpi_or_chart_definition": "Action shortcuts and recent scenarios to reduce time-to-decision.",
        "formula": "No direct formula. This is workflow control.",
        "inputs": ["saved scenarios", "navigation state"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: scenario list reflects current planning cadence. Risk: stale scenario selected by mistake.",
        "decision_supported": "Where to branch next in the analysis flow.",
        "recommended_next_action": "Open the module matching your current decision intent (impact, curve, allocation, simulation).",
        "misinterpretation_risks": "Assuming scenario recency equals scenario quality.",
        "data_freshness_or_caveats": "Scenario list depends on saved state and may include exploratory drafts.",
    },
    "monthly-trend": {
        "title": "Monthly Incremental Trend",
        "business_question": "When in the year did incremental sales accelerate or stall?",
        "kpi_name": "Monthly Incremental Sales",
        "bbox": [110, 620, 1450, 330],
        "kpi_or_chart_definition": "Time-series of incremental contribution by month.",
        "formula": "Monthly Incremental_t = Σ Incremental_{i,t} across channels i for month t.",
        "inputs": ["contribution rows by month", "incremental values"],
        "unit_and_scale": "Currency or volume proxy, monthly granularity.",
        "how_to_read_good_vs_risk": "Good: predictable peaks align with campaign timing. Risk: unexplained volatility or declining trend.",
        "decision_supported": "Whether to shift spend timing and campaign cadence.",
        "recommended_next_action": "Investigate channel-level contributions for abnormal months.",
        "misinterpretation_risks": "Confusing seasonal base effects with media-driven uplift.",
        "data_freshness_or_caveats": "Monthly aggregation can hide intra-month campaign dynamics.",
    },
    "channel-mix": {
        "title": "Channel Mix",
        "business_question": "Which channels currently create the largest share of incremental impact?",
        "kpi_name": "Contribution Share",
        "bbox": [100, 610, 1460, 340],
        "kpi_or_chart_definition": "Distribution of incremental effect across channels.",
        "formula": "Share_i = Incremental_i / Σ Incremental_j.",
        "inputs": ["channel incremental totals"],
        "unit_and_scale": "Percent share [0..100%].",
        "how_to_read_good_vs_risk": "Good: effect share is balanced with strategic intent. Risk: over-concentration in one channel.",
        "decision_supported": "Whether to rebalance channel mix or protect strong performers.",
        "recommended_next_action": "Use Response Curves to confirm headroom before scaling top-share channels.",
        "misinterpretation_risks": "Assuming highest share channel always has best marginal return.",
        "data_freshness_or_caveats": "Shares depend on model decomposition assumptions.",
    },
    "cross-product-roas": {
        "title": "Cross-Product ROAS",
        "business_question": "How does this product’s efficiency compare with peers?",
        "kpi_name": "Portfolio ROAS",
        "bbox": [120, 690, 1420, 260],
        "kpi_or_chart_definition": "Portfolio-level ROAS comparison across products.",
        "formula": "ROAS_product = Incremental_product / Spend_product.",
        "inputs": ["product-level spend totals", "product-level incremental totals"],
        "unit_and_scale": "Ratio (x).",
        "how_to_read_good_vs_risk": "Good: target product competitive or improving vs peers. Risk: persistent underperformance.",
        "decision_supported": "Portfolio prioritization across brands/products.",
        "recommended_next_action": "If lagging peers, run allocator and scenario simulations for recovery options.",
        "misinterpretation_risks": "Comparing products with materially different lifecycle stages without context.",
        "data_freshness_or_caveats": "Cross-product comparability depends on consistent model calibration.",
    },
    "annual-volume-impact": {
        "title": "Annual Volume Impact",
        "business_question": "Which channels contributed most each month in relative terms?",
        "kpi_name": "Monthly Share-of-Impact",
        "bbox": [95, 320, 1470, 500],
        "kpi_or_chart_definition": "Stacked percent chart of monthly channel impact composition.",
        "formula": "Monthly Share_{i,t} = Incremental_{i,t} / Σ_k Incremental_{k,t}.",
        "inputs": ["channel-month incremental matrix"],
        "unit_and_scale": "Percent per month.",
        "how_to_read_good_vs_risk": "Good: composition aligns with strategic channel roles. Risk: sudden unexplained channel dominance shifts.",
        "decision_supported": "Whether channel role mix changed and needs budget correction.",
        "recommended_next_action": "Investigate months with abrupt share shifts using channel absolute contributions.",
        "misinterpretation_risks": "Reading percent stack without absolute volume context.",
        "data_freshness_or_caveats": "Percent view can hide months with low absolute impact.",
    },
    "channel-contributions": {
        "title": "Channel Contributions",
        "business_question": "What is the absolute incremental impact by channel over time?",
        "kpi_name": "Absolute Incremental Contribution",
        "bbox": [90, 330, 1480, 470],
        "kpi_or_chart_definition": "Absolute stacked area of channel incremental outcomes.",
        "formula": "Incremental_{i,t} from decomposition, aggregated by channel i and time t.",
        "inputs": ["contribution rows"],
        "unit_and_scale": "Currency or response units, absolute scale.",
        "how_to_read_good_vs_risk": "Good: high-impact channels stable and explainable. Risk: volatility without business explanation.",
        "decision_supported": "Which channels should be defended or challenged in planning.",
        "recommended_next_action": "Use Response Curves to verify if top absolute contributors still have marginal headroom.",
        "misinterpretation_risks": "Confusing large absolute impact with high efficiency.",
        "data_freshness_or_caveats": "Dependent on decomposition quality and model version.",
    },
    "export-copy-controls": {
        "title": "Audit Export Controls",
        "business_question": "Can I share raw evidence for finance/analytics validation?",
        "kpi_name": "Auditability",
        "bbox": [960, 930, 560, 90],
        "kpi_or_chart_definition": "Controls for exporting and copying underlying contribution rows.",
        "formula": "No KPI formula; enables traceability of already computed rows.",
        "inputs": ["contribution table"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: exports match visible values. Risk: decision made without audit handoff.",
        "decision_supported": "Whether the analysis is ready for governance review.",
        "recommended_next_action": "Export dataset when presenting to finance or model governance.",
        "misinterpretation_risks": "Assuming exported rows include context filters unless verified.",
        "data_freshness_or_caveats": "Snapshot reflects current filter state.",
    },
    "next-step-prompt": {
        "title": "Next Step Prompt",
        "business_question": "What is the recommended next workflow step?",
        "kpi_name": "Guided Workflow",
        "bbox": [90, 920, 1460, 110],
        "kpi_or_chart_definition": "Contextual CTA that routes users to the next analytical action.",
        "formula": "No direct formula.",
        "inputs": ["current tab state"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: prompt aligns with unresolved decision. Risk: skipping intermediate validation tabs.",
        "decision_supported": "Which module to open next.",
        "recommended_next_action": "Follow prompt only after validating current tab’s key evidence.",
        "misinterpretation_risks": "Treating prompt as a recommendation engine.",
        "data_freshness_or_caveats": "Prompt is static workflow guidance, not dynamic optimization.",
    },
    "channel-select": {
        "title": "Channel Selector",
        "business_question": "Which channels should be compared for marginal return and saturation?",
        "kpi_name": "Curve Scope",
        "bbox": [90, 170, 1460, 180],
        "kpi_or_chart_definition": "Toggle chips controlling which channel curves are visible.",
        "formula": "No direct KPI; controls subset C used in chart metrics.",
        "inputs": ["available channel curves"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: focus on channels under active budget discussion. Risk: hidden channels not reviewed.",
        "decision_supported": "Scope of channel comparison.",
        "recommended_next_action": "Select 2-4 competing channels before reading curve metrics.",
        "misinterpretation_risks": "Interpreting chart as portfolio view when only subset is selected.",
        "data_freshness_or_caveats": "Selected channels persist only in current session state.",
    },
    "main-curve-chart": {
        "title": "Response Curve (Revenue)",
        "business_question": "How much incremental outcome is expected as spend increases?",
        "kpi_name": "Response Curve",
        "bbox": [100, 300, 1450, 600],
        "kpi_or_chart_definition": "Spend-response relationship by channel with current spend marker.",
        "formula": "Saturation(x)=x^α/(x^α+λ^α); Response(x)=Scale×Saturation(x).",
        "inputs": ["curve parameters α, λ", "spend x", "calibration scale"],
        "unit_and_scale": "X: currency spend; Y: incremental response (currency/units).",
        "how_to_read_good_vs_risk": "Good: selected channels show steep slope near current spend. Risk: flat slope indicates saturation.",
        "decision_supported": "Where incremental budget is likely to return most.",
        "recommended_next_action": "Shift marginal budget toward steeper curves, then validate in allocator.",
        "misinterpretation_risks": "Treating long-run curve extrapolation as guaranteed realized outcome.",
        "data_freshness_or_caveats": "Curve uncertainty and calibration depend on model artifacts.",
    },
    "mroi-view": {
        "title": "Marginal ROI View",
        "business_question": "What does the next unit of spend likely return right now?",
        "kpi_name": "mROI",
        "bbox": [100, 300, 1450, 600],
        "kpi_or_chart_definition": "Slope view of response curve showing marginal return.",
        "formula": "mROI ≈ ΔResponse/ΔSpend around current spend.",
        "inputs": ["adjacent response points", "spend increments"],
        "unit_and_scale": "Ratio per currency unit.",
        "how_to_read_good_vs_risk": "Good: mROI above strategic hurdle rate. Risk: mROI below hurdle indicates inefficient increment.",
        "decision_supported": "Which channel gets the next incremental budget dollar/euro.",
        "recommended_next_action": "Set or confirm channel-level stop/go thresholds using mROI ranking.",
        "misinterpretation_risks": "Confusing average ROI with marginal ROI.",
        "data_freshness_or_caveats": "Locally estimated slope can be noisy where curve points are sparse.",
    },
    "saturation-view": {
        "title": "Saturation View",
        "business_question": "How close is each channel to its practical ceiling?",
        "kpi_name": "Saturation %",
        "bbox": [100, 300, 1450, 600],
        "kpi_or_chart_definition": "Normalized curve expressing distance to channel ceiling.",
        "formula": "Saturation% = Response(x) / MaxResponse × 100.",
        "inputs": ["current response", "channel max response"],
        "unit_and_scale": "Percent [0..100%].",
        "how_to_read_good_vs_risk": "Good: lower saturation indicates growth headroom. Risk: high saturation suggests diminishing returns.",
        "decision_supported": "Whether to scale a channel or hold/reduce incremental spend.",
        "recommended_next_action": "Reallocate from >70% saturation channels to lower-saturation channels if mROI also supports it.",
        "misinterpretation_risks": "Assuming identical saturation thresholds across all channel types.",
        "data_freshness_or_caveats": "Derived from modelled curve ceiling, not a hard operational cap.",
    },
    "channel-metric-cards": {
        "title": "Per-Channel Metric Cards",
        "business_question": "What are current spend, response, and efficiency signals per selected channel?",
        "kpi_name": "Channel Snapshot Metrics",
        "bbox": [95, 860, 1460, 150],
        "kpi_or_chart_definition": "Compact channel-level metrics aligned with currently selected curve mode.",
        "formula": "Current ROI_i = Current Response_i / Current Spend_i; Headroom_i = 1 - Saturation_i.",
        "inputs": ["current spend", "current response", "saturation"],
        "unit_and_scale": "Currency and ratios.",
        "how_to_read_good_vs_risk": "Good: strong current ROI with meaningful headroom. Risk: high spend with low marginal gain.",
        "decision_supported": "Immediate shortlist for increase, hold, or cut decisions.",
        "recommended_next_action": "Carry shortlisted channels into allocator constraints.",
        "misinterpretation_risks": "Comparing channels without considering confidence interval width.",
        "data_freshness_or_caveats": "Values are model-based summaries at current spend.",
    },
    "scenario-builder-optimize": {
        "title": "Scenario Builder (Optimize)",
        "business_question": "What constraints and objective should shape the optimized plan?",
        "kpi_name": "Optimization Setup",
        "bbox": [95, 180, 1460, 260],
        "kpi_or_chart_definition": "Inputs for objective, budget band, and channel-level min/max constraints.",
        "formula": "max Σ Response_i(Spend_i) subject to Σ Spend_i = Budget and Min_i ≤ Spend_i ≤ Max_i.",
        "inputs": ["objective", "budget range", "channel constraints", "response curves"],
        "unit_and_scale": "Currency and percentages/multipliers.",
        "how_to_read_good_vs_risk": "Good: constraints reflect real business guardrails. Risk: unrealistic bounds force poor allocations.",
        "decision_supported": "Formal optimization setup before running scenario.",
        "recommended_next_action": "Set realistic min/max by channel, then run and inspect optimization metrics.",
        "misinterpretation_risks": "Treating optimizer output as valid when constraints are unrealistic.",
        "data_freshness_or_caveats": "Output quality depends on curve quality and constraint realism.",
    },
    "optimization-metrics-table": {
        "title": "Optimization Metrics",
        "business_question": "Does the optimized scenario materially improve outcomes vs current plan?",
        "kpi_name": "Scenario Outcome Metrics",
        "bbox": [100, 450, 1440, 170],
        "kpi_or_chart_definition": "Current vs optimized totals and deltas for spend, incremental sales, profit, and ROI.",
        "formula": "ROI = Incremental/Spend; Profit = Incremental - Spend; ΔMetric%=(Optimized-Current)/Current×100.",
        "inputs": ["current allocation", "optimized allocation", "response estimates"],
        "unit_and_scale": "Currency, ratio, percent delta.",
        "how_to_read_good_vs_risk": "Good: positive incremental and profit deltas with acceptable risk. Risk: ROI gains driven by unrealistic cuts or noisy channels.",
        "decision_supported": "Go/no-go on moving forward with this scenario.",
        "recommended_next_action": "If uplift is material, export and validate via simulator sensitivity checks.",
        "misinterpretation_risks": "Overweighting ROI without checking absolute outcome changes.",
        "data_freshness_or_caveats": "For what-if mode, server curve interpolation drives estimates.",
    },
    "scenario-results-table": {
        "title": "Scenario Results Table",
        "business_question": "Which specific channels increase or decrease in the optimized plan?",
        "kpi_name": "Channel-Level Allocation Deltas",
        "bbox": [100, 610, 1440, 190],
        "kpi_or_chart_definition": "Row-level channel deltas between current and optimized spends/shares.",
        "formula": "Delta_i = Optimized_i - Current_i; Delta%_i = Delta_i / Current_i × 100.",
        "inputs": ["channel current spend", "channel optimized spend"],
        "unit_and_scale": "Currency and percent.",
        "how_to_read_good_vs_risk": "Good: reallocations align with curve headroom and business guardrails. Risk: large swings in uncertain channels.",
        "decision_supported": "Which channel-level moves to operationalize.",
        "recommended_next_action": "Flag large positive/negative deltas for commercial team validation.",
        "misinterpretation_risks": "Assuming all channel deltas are equally executable.",
        "data_freshness_or_caveats": "Execution feasibility is external to model outputs.",
    },
    "budget-split-chart": {
        "title": "Budget Split Chart",
        "business_question": "How does spend share shift between current and optimized allocation?",
        "kpi_name": "Current vs Optimized Share",
        "bbox": [100, 800, 1440, 190],
        "kpi_or_chart_definition": "Visual side-by-side of current and optimized channel budget shares.",
        "formula": "Share_i = Spend_i / Σ Spend_j (computed for current and optimized plans).",
        "inputs": ["current spends", "optimized spends"],
        "unit_and_scale": "Percent share.",
        "how_to_read_good_vs_risk": "Good: share moves are strategic and explainable. Risk: extreme concentration shifts.",
        "decision_supported": "Communication readiness of reallocation narrative.",
        "recommended_next_action": "Use this chart to present high-level reallocation story to stakeholders.",
        "misinterpretation_risks": "Reading share change without absolute spend context.",
        "data_freshness_or_caveats": "Share visuals mask absolute budget size changes.",
    },
    "planned-scenario-panel": {
        "title": "Planned Scenario Panel",
        "business_question": "Is this scenario packaged and ready to transfer to simulation/approval?",
        "kpi_name": "Scenario Packaging",
        "bbox": [100, 910, 1440, 100],
        "kpi_or_chart_definition": "Scenario naming, save/export, and transfer actions.",
        "formula": "No KPI formula; operational packaging step.",
        "inputs": ["scenario rows", "scenario metadata"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: scenario labeled clearly and saved. Risk: ambiguous scenario naming causes misuse.",
        "decision_supported": "Whether scenario is governance-ready.",
        "recommended_next_action": "Save with explicit objective and date context, then open in Simulator.",
        "misinterpretation_risks": "Confusing draft and approved scenarios.",
        "data_freshness_or_caveats": "Scenario snapshot may drift if rerun with different model version.",
    },
    "scenario-builder-what-if": {
        "title": "Scenario Builder (What-If)",
        "business_question": "What happens if I manually nudge channel spends up or down?",
        "kpi_name": "What-If Stress Test",
        "bbox": [95, 180, 1460, 260],
        "kpi_or_chart_definition": "Manual adjustment controls with real-time impact estimation.",
        "formula": "NewSpend_i = CurrentSpend_i × (1 + Adj%_i); NewResponse = Σ Response_i(NewSpend_i).",
        "inputs": ["manual adjustment %", "current spend", "response curves"],
        "unit_and_scale": "Percent adjustments and currency outcomes.",
        "how_to_read_good_vs_risk": "Good: scenario remains beneficial under realistic manual perturbations. Risk: fragile scenario collapses under small changes.",
        "decision_supported": "Sensitivity of recommended plan.",
        "recommended_next_action": "Stress high-risk channels before approval.",
        "misinterpretation_risks": "Treating what-if as optimization output.",
        "data_freshness_or_caveats": "What-if uses current model state and may change with updated curves.",
    },
    "header-and-saved-scenarios": {
        "title": "Simulator Header & Saved Scenarios",
        "business_question": "Which scenario baseline am I currently testing?",
        "kpi_name": "Scenario Context",
        "bbox": [95, 150, 1460, 230],
        "kpi_or_chart_definition": "Scenario identity, save/load controls, and metadata context.",
        "formula": "No KPI formula; context control.",
        "inputs": ["scenario store", "selected scenario metadata"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: clear scenario provenance. Risk: evaluating wrong loaded scenario.",
        "decision_supported": "Scope and provenance control for simulation runs.",
        "recommended_next_action": "Confirm scenario name/version before interpreting any metric deltas.",
        "misinterpretation_risks": "Assuming all scenarios share identical objective and constraints.",
        "data_freshness_or_caveats": "Saved scenarios persist and can become outdated.",
    },
    "channel-multipliers-panel": {
        "title": "Channel Multipliers Panel",
        "business_question": "How do manual multiplier changes alter expected outcome by channel?",
        "kpi_name": "Spend Multipliers",
        "bbox": [95, 400, 480, 600],
        "kpi_or_chart_definition": "Slider-based multipliers applied to baseline spend by channel.",
        "formula": "ManualSpend_i = BaselineSpend_i × Multiplier_i.",
        "inputs": ["baseline spend", "manual multiplier"],
        "unit_and_scale": "Multiplier (x).",
        "how_to_read_good_vs_risk": "Good: moderate moves reveal robust direction. Risk: extreme multipliers outside feasible operations.",
        "decision_supported": "Sensitivity of channel recommendations.",
        "recommended_next_action": "Test downside and upside bands for top reallocated channels.",
        "misinterpretation_risks": "Ignoring execution limits when using high multipliers.",
        "data_freshness_or_caveats": "Applies to current loaded scenario only.",
    },
    "representative-channel-curve-card": {
        "title": "Representative Curve Card",
        "business_question": "How far did manual/imported points move from baseline on the response curve?",
        "kpi_name": "Baseline vs Imported vs Manual Dots",
        "bbox": [600, 400, 960, 300],
        "kpi_or_chart_definition": "Per-channel response curve with baseline/imported/manual markers.",
        "formula": "Delta_i = Response_i(ManualSpend_i) - Response_i(BaselineSpend_i).",
        "inputs": ["curve points", "baseline spend", "manual spend", "imported spend"],
        "unit_and_scale": "Incremental response units and spend units.",
        "how_to_read_good_vs_risk": "Good: manual dot lands in high-slope region. Risk: manual dot pushed into flat saturation zone.",
        "decision_supported": "Whether channel-level adjustment is value-accretive.",
        "recommended_next_action": "Prefer changes that move points along steep curve sections.",
        "misinterpretation_risks": "Comparing channels without accounting for curve shape differences.",
        "data_freshness_or_caveats": "Curve shape tied to selected model version.",
    },
    "headline-and-trust-block": {
        "title": "Insight Headline & Trust",
        "business_question": "What is the headline recommendation and how much should I trust it?",
        "kpi_name": "Trust + Executive Summary",
        "bbox": [90, 160, 1460, 230],
        "kpi_or_chart_definition": "Executive summary panel with top performer and trust indicators.",
        "formula": "Trust/grade is computed server-side from model diagnostics and uncertainty signals.",
        "inputs": ["PyMC trust score", "average ROI", "saturation summaries"],
        "unit_and_scale": "Letter grade and summary KPIs.",
        "how_to_read_good_vs_risk": "Good: strong trust with coherent channel story. Risk: weak trust with aggressive recommendation.",
        "decision_supported": "Whether to act immediately or demand additional validation.",
        "recommended_next_action": "If trust is weak, review diagnostics and run conservative pilot.",
        "misinterpretation_risks": "Taking headline recommendation without confidence context.",
        "data_freshness_or_caveats": "Trust available only when PyMC artifacts are present.",
    },
    "channel-performance-table": {
        "title": "Channel Performance Table",
        "business_question": "Which channels are strongest after accounting for ROI and confidence?",
        "kpi_name": "ROI / CI / Confidence by Channel",
        "bbox": [95, 420, 1460, 280],
        "kpi_or_chart_definition": "Ranked table of channel performance metrics.",
        "formula": "ROI_i = Incremental_i / Spend_i; CI from posterior quantiles (e.g., 5th/95th).",
        "inputs": ["channel spend", "channel incremental", "uncertainty quantiles", "confidence probability"],
        "unit_and_scale": "Ratio, interval, percent.",
        "how_to_read_good_vs_risk": "Good: high ROI with narrow CI and high confidence. Risk: high ROI but wide CI / low confidence.",
        "decision_supported": "Prioritization of channels for scale vs hold.",
        "recommended_next_action": "Prioritize channels with strong ROI and robust confidence simultaneously.",
        "misinterpretation_risks": "Ranking only by point estimate ROI.",
        "data_freshness_or_caveats": "CI/confidence unavailable in basic data mode.",
    },
    "radar-chart": {
        "title": "Channel Radar",
        "business_question": "How do channels compare across multiple dimensions at once?",
        "kpi_name": "Multi-Dimension Channel Score",
        "bbox": [90, 710, 720, 300],
        "kpi_or_chart_definition": "Radar profile combining ROI, confidence/headroom/adstock proxies.",
        "formula": "Axis scores are normalized to 0..100 per metric for comparability.",
        "inputs": ["ROI", "confidence", "headroom", "adstock or spend share"],
        "unit_and_scale": "Normalized score [0..100].",
        "how_to_read_good_vs_risk": "Good: balanced, consistently strong shape. Risk: spiky profile with weak confidence/headroom.",
        "decision_supported": "Balanced portfolio-style channel selection.",
        "recommended_next_action": "Use radar to avoid over-optimizing on one metric only.",
        "misinterpretation_risks": "Interpreting area size as absolute value without axis context.",
        "data_freshness_or_caveats": "Metric set differs between PyMC and base mode.",
    },
    "efficiency-frontier": {
        "title": "Efficiency Frontier",
        "business_question": "Which channels lie on the efficient spend-vs-return frontier?",
        "kpi_name": "Spend vs ROI Frontier",
        "bbox": [830, 710, 730, 300],
        "kpi_or_chart_definition": "Scatter of channel spend versus ROI to identify efficient/inefficient positions.",
        "formula": "Each point: (x=Spend_i, y=ROI_i). Frontier channels maximize ROI for given spend.",
        "inputs": ["channel spend", "channel ROI"],
        "unit_and_scale": "Currency and ratio.",
        "how_to_read_good_vs_risk": "Good: scaled channels remain near frontier. Risk: heavy spend in low-ROI area.",
        "decision_supported": "Reallocation from inefficient to efficient channels.",
        "recommended_next_action": "Target channels below frontier for corrective action.",
        "misinterpretation_risks": "Ignoring confidence/CI while interpreting frontier.",
        "data_freshness_or_caveats": "Frontier interpretation should be paired with uncertainty checks.",
    },
    "adstock-block": {
        "title": "Adstock / Carryover",
        "business_question": "Which channels create delayed impact and how long does it persist?",
        "kpi_name": "Carryover Dynamics",
        "bbox": [90, 910, 1460, 120],
        "kpi_or_chart_definition": "Carryover characteristics from adstock analysis.",
        "formula": "Half-life (periods) derived from channel adstock decay parameters (server-computed).",
        "inputs": ["adstock parameters", "posterior summaries"],
        "unit_and_scale": "Time periods and normalized carryover indicators.",
        "how_to_read_good_vs_risk": "Good: carryover assumptions align with known channel behavior. Risk: mismatch implies model misspecification.",
        "decision_supported": "Timing and pacing decisions for campaigns.",
        "recommended_next_action": "Adjust pacing for channels with long carryover to avoid over-frequency.",
        "misinterpretation_risks": "Assuming carryover means immediate performance.",
        "data_freshness_or_caveats": "Available only with PyMC adstock outputs.",
    },
    "recommendations-and-suggested-action": {
        "title": "Recommendations",
        "business_question": "What concrete business action is suggested from current model evidence?",
        "kpi_name": "Suggested Action",
        "bbox": [90, 900, 1460, 120],
        "kpi_or_chart_definition": "Action recommendations generated from model outputs and constraints.",
        "formula": "No single formula; recommendation is a rule-based synthesis of ROI, saturation, and diagnostics.",
        "inputs": ["ROI signals", "saturation", "trust/diagnostics", "scenario outcomes"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: recommendation aligns with tab evidence. Risk: recommendation conflicts with weak trust signals.",
        "decision_supported": "Action commitment and owner alignment.",
        "recommended_next_action": "Translate recommendation into a scenario and validate in Simulator.",
        "misinterpretation_risks": "Treating recommendation as deterministic truth.",
        "data_freshness_or_caveats": "Recommendation quality depends on artifact completeness.",
    },
    "diagnostics-block": {
        "title": "Diagnostics",
        "business_question": "Do diagnostics reveal reasons to limit confidence in the recommendation?",
        "kpi_name": "Model Diagnostics",
        "bbox": [90, 900, 1460, 120],
        "kpi_or_chart_definition": "Diagnostic checks for model health and anomalies.",
        "formula": "Diagnostic metrics are computed server-side from model fit and uncertainty outputs.",
        "inputs": ["fit metrics", "sanity checks", "uncertainty diagnostics"],
        "unit_and_scale": "Mixed metrics and statuses.",
        "how_to_read_good_vs_risk": "Good: no severe flags. Risk: material warnings that invalidate aggressive changes.",
        "decision_supported": "Confidence gating before operational rollout.",
        "recommended_next_action": "If red flags appear, run conservative pilot and revisit model.",
        "misinterpretation_risks": "Ignoring diagnostics when headline upside looks attractive.",
        "data_freshness_or_caveats": "Diagnostics can differ by engine/tier/version.",
    },
    "configuration-selection-panel": {
        "title": "Configuration Selection",
        "business_question": "Am I evaluating the correct market/product/version/tier before making decisions?",
        "kpi_name": "Model Context Selection",
        "bbox": [90, 170, 500, 620],
        "kpi_or_chart_definition": "Selectors defining active analytical context and tier availability.",
        "formula": "No KPI formula; selection determines all downstream data queries.",
        "inputs": ["market list", "product list", "version list", "tier availability"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: context matches intended decision scope. Risk: wrong version/tier selected.",
        "decision_supported": "Scope and validity of all downstream analysis.",
        "recommended_next_action": "Lock selection before sharing outputs externally.",
        "misinterpretation_risks": "Comparing outputs from mismatched versions.",
        "data_freshness_or_caveats": "Latest may move as new runs publish.",
    },
    "candidate-preview-card": {
        "title": "Candidate Preview",
        "business_question": "Is the active model deployment-ready from a quality perspective?",
        "kpi_name": "Model Candidate Health",
        "bbox": [120, 690, 420, 270],
        "kpi_or_chart_definition": "Snapshot of model engine, quality metrics, and deployment state.",
        "formula": "R² and MAPE sourced from model_stats; grade/quality badges are threshold-based.",
        "inputs": ["model_stats", "engine metadata", "tier metadata"],
        "unit_and_scale": "Percent and status labels.",
        "how_to_read_good_vs_risk": "Good: strong fit with acceptable decomposition error. Risk: poor fit but still active.",
        "decision_supported": "Whether to trust and activate/deploy selected model.",
        "recommended_next_action": "If weak metrics, switch version or escalate for model retraining.",
        "misinterpretation_risks": "Using one metric only to judge model readiness.",
        "data_freshness_or_caveats": "Depends on selected version and tier.",
    },
    "one-pager-metric-cards": {
        "title": "One-Pager Metrics",
        "business_question": "Does this model clear quality thresholds for business use?",
        "kpi_name": "Model Quality One-Pager",
        "bbox": [590, 220, 970, 220],
        "kpi_or_chart_definition": "Core quality metrics summarizing fit and error.",
        "formula": "R² = 1 - SSE/SST; MAPE = mean(|Actual-Forecast|/Actual).",
        "inputs": ["actuals", "fitted values", "errors"],
        "unit_and_scale": "R² unitless, MAPE percent.",
        "how_to_read_good_vs_risk": "Good: high R² with controlled MAPE. Risk: low R² or high MAPE undermines planning confidence.",
        "decision_supported": "Model go/no-go for operational planning.",
        "recommended_next_action": "If below threshold, prefer conservative changes or alternate version.",
        "misinterpretation_risks": "Assuming high R² guarantees robust channel-level allocation.",
        "data_freshness_or_caveats": "Out-of-sample diagnostics should also be considered when available.",
    },
    "efficiency-chart": {
        "title": "Efficiency Chart",
        "business_question": "Which channels over- or under-deliver relative to spend share?",
        "kpi_name": "Spend Share vs Effect Share",
        "bbox": [590, 450, 970, 240],
        "kpi_or_chart_definition": "Compares spend share with effect share by channel.",
        "formula": "Efficiency Ratio_i = EffectShare_i / SpendShare_i.",
        "inputs": ["channel spend share", "channel effect share"],
        "unit_and_scale": "Ratio (1.0 = proportional).",
        "how_to_read_good_vs_risk": "Good: ratio >1 for priority channels. Risk: heavy channels with ratio <1.",
        "decision_supported": "Identify over-invested and under-invested channels.",
        "recommended_next_action": "Rebalance budget from persistently <1.0 channels toward >1.0 channels with headroom.",
        "misinterpretation_risks": "Ignoring minimum strategic spend requirements.",
        "data_freshness_or_caveats": "Effect share is model-derived, not direct causal proof.",
    },
    "driver-contribution-chart": {
        "title": "Driver Contribution",
        "business_question": "What proportion of outcome is explained by each driver category?",
        "kpi_name": "Driver Mix",
        "bbox": [590, 700, 970, 240],
        "kpi_or_chart_definition": "Contribution breakdown across media and non-media drivers.",
        "formula": "DriverShare_d = Contribution_d / Σ Contributions.",
        "inputs": ["driver-level contributions"],
        "unit_and_scale": "Percent share.",
        "how_to_read_good_vs_risk": "Good: media contribution level is plausible and stable. Risk: implausible dominance by one driver category.",
        "decision_supported": "Balance between media actions and contextual/non-media levers.",
        "recommended_next_action": "Investigate any large driver shift before committing big allocation changes.",
        "misinterpretation_risks": "Interpreting contextual drivers as directly controllable media levers.",
        "data_freshness_or_caveats": "Driver grouping rules can vary by model configuration.",
    },
    "model-analysis-table": {
        "title": "Model Analysis Table",
        "business_question": "Where are the diagnostic strengths and weaknesses that affect business risk?",
        "kpi_name": "Detailed Model Verification",
        "bbox": [590, 910, 970, 120],
        "kpi_or_chart_definition": "Table of model checks and verification outputs.",
        "formula": "Composite of model diagnostics computed server-side.",
        "inputs": ["fit metrics", "diagnostic flags", "validation outputs"],
        "unit_and_scale": "Mixed metric types.",
        "how_to_read_good_vs_risk": "Good: broad pass with minor warnings only. Risk: major failed checks.",
        "decision_supported": "Risk-adjusted adoption of model outputs.",
        "recommended_next_action": "Escalate unresolved red flags before wide rollout.",
        "misinterpretation_risks": "Overlooking failed checks due to strong headline KPIs.",
        "data_freshness_or_caveats": "Verification output depends on selected version/tier.",
    },
    "advanced-map-view": {
        "title": "Territory Map",
        "business_question": "Which territories show strongest or weakest modeled effects?",
        "kpi_name": "Territory Effect Intensity",
        "bbox": [95, 190, 680, 460],
        "kpi_or_chart_definition": "Choropleth/heatmap of territorial effect intensity.",
        "formula": "TerritoryEffect_t = Σ channel effects in territory t (hierarchical model output).",
        "inputs": ["territory effects payload", "selected channel filter"],
        "unit_and_scale": "Relative intensity / beta-derived effect units.",
        "how_to_read_good_vs_risk": "Good: regional differences are interpretable with market context. Risk: noisy territory outliers drive overreaction.",
        "decision_supported": "Regional targeting and budget localization strategy.",
        "recommended_next_action": "Use map outliers to prioritize deeper territory review.",
        "misinterpretation_risks": "Treating color intensity as absolute sales magnitude.",
        "data_freshness_or_caveats": "Available only in advanced tier with territory artifacts.",
    },
    "territory-detail-table": {
        "title": "Territory Detail Table",
        "business_question": "How do territories compare on channel-specific effect metrics?",
        "kpi_name": "Territory Channel Detail",
        "bbox": [95, 700, 1460, 320],
        "kpi_or_chart_definition": "Sortable table of territory-level metrics and channel effects.",
        "formula": "Rank by TerritoryEffect_t or selected channel beta/impact metric.",
        "inputs": ["territory table payload"],
        "unit_and_scale": "Effect values and ranks.",
        "how_to_read_good_vs_risk": "Good: pattern supports differentiated execution. Risk: random-like rank instability.",
        "decision_supported": "Where to tailor channel intensity by territory.",
        "recommended_next_action": "Build regional action list from top/bottom territory clusters.",
        "misinterpretation_risks": "Overfitting field actions to small modeled differences.",
        "data_freshness_or_caveats": "Territory granularity may mask local heterogeneity.",
    },
    "channel-dispersion-cards": {
        "title": "Channel Dispersion",
        "business_question": "How uneven is channel effect across territories?",
        "kpi_name": "Dispersion / Variance",
        "bbox": [770, 210, 780, 430],
        "kpi_or_chart_definition": "Cards summarizing channel variability across territories.",
        "formula": "Dispersion_i = (max_i - min_i) / max_i × 100.",
        "inputs": ["territory-level channel effects"],
        "unit_and_scale": "Percent dispersion.",
        "how_to_read_good_vs_risk": "Good: manageable dispersion for nationally standardized channels. Risk: high dispersion suggests local strategy needed.",
        "decision_supported": "National vs territory-tailored channel strategy.",
        "recommended_next_action": "High-dispersion channels should get region-specific planning.",
        "misinterpretation_risks": "Interpreting dispersion as certainty rather than variability.",
        "data_freshness_or_caveats": "Sensitive to territory sample coverage.",
    },
    "product-comparison-table": {
        "title": "Product Comparison",
        "business_question": "How does this product compare to others in geographic performance context?",
        "kpi_name": "Cross-Product Territory Comparison",
        "bbox": [90, 900, 1460, 120],
        "kpi_or_chart_definition": "Comparative table across products or lines in geography module.",
        "formula": "Comparison metrics are server-computed aggregations by product and geography.",
        "inputs": ["products summary", "territory summaries"],
        "unit_and_scale": "Mixed (currency, ratios, ranks).",
        "how_to_read_good_vs_risk": "Good: consistent relative performance story. Risk: contradictory signals without context.",
        "decision_supported": "Portfolio trade-offs across products/regions.",
        "recommended_next_action": "Prioritize products/regions with strongest controllable uplift potential.",
        "misinterpretation_risks": "Comparing incomparable products without lifecycle normalization.",
        "data_freshness_or_caveats": "Depends on available products in selected context.",
    },
    "basic-tier-locked-placeholder": {
        "title": "Advanced Tier Lock",
        "business_question": "Why is territory analysis unavailable and what unlocks it?",
        "kpi_name": "Tier Gate",
        "bbox": [260, 320, 980, 360],
        "kpi_or_chart_definition": "Access gate explaining advanced tier requirement.",
        "formula": "No KPI; capability gating based on selected model tier.",
        "inputs": ["selected tier", "available tiers"],
        "unit_and_scale": "N/A",
        "how_to_read_good_vs_risk": "Good: users clearly understand unlock path. Risk: misinterpreting lock as data failure.",
        "decision_supported": "Whether to switch tier before geography analysis.",
        "recommended_next_action": "Go to Settings and switch to Advanced tier when available.",
        "misinterpretation_risks": "Raising data-quality incidents for an intentional tier gate.",
        "data_freshness_or_caveats": "Advanced tier availability is product/version-specific.",
    },
}

CRITICAL_WORKED_EXAMPLES = {
    "TAB_HOME_KPI_ROW": "Example: if total incremental = 3.2M and total spend = 1.6M, ROI = 3.2/1.6 = 2.0x.",
    "TAB_SALES_IMPACT_KPI_ROW": "Example: if SSE=120 and SST=400, R² = 1 - 120/400 = 0.70.",
    "TAB_RESPONSE_CURVES_MAIN_CHART_REVENUE": "Example: if spend moves from 100k to 120k and response from 240k to 268k, local mROI ≈ (268-240)/(120-100)=1.4x.",
    "TAB_BUDGET_ALLOCATOR_OPTIMIZATION_METRICS": "Example: current 2.0M incremental on 1.4M spend gives 1.43x ROI; optimized 2.3M on 1.5M gives 1.53x ROI, uplift +0.10x.",
    "TAB_SIMULATOR_OPTIMIZATION_METRICS": "Example: baseline volume 100k plus summed curve deltas +8k yields simulated 108k volume (+8%).",
    "TAB_INSIGHTS_CHANNEL_PERFORMANCE_TABLE": "Example: channel spend 300k and incremental 540k implies ROI 1.8x; CI [1.2,2.3] indicates upside with uncertainty.",
    "TAB_SETTINGS_ONE_PAGER_METRIC_CARDS": "Example: Actual=100, Forecast=92 gives abs pct error 8%; aggregate these for MAPE.",
}

CALL_OUT_OVERRIDES = {
    "TAB_HOME_KPI_ROW": {
        "title": "Topline KPI Row",
        "business_question": "Do spend and incremental outcomes justify action now?",
        "kpi_name": "Spend / Incremental / ROI",
    },
    "TAB_SALES_IMPACT_KPI_ROW": {
        "title": "Model Credibility KPIs",
        "business_question": "Is the model quality adequate for planning decisions?",
        "kpi_name": "Model R² and Totals",
    },
    "TAB_RESPONSE_CURVES_MAIN_CHART_REVENUE": {
        "title": "Primary Response Curves",
        "business_question": "Where is additional spend still productive?",
        "kpi_name": "Spend-Response Curve",
    },
    "TAB_BUDGET_ALLOCATOR_OPTIMIZATION_METRICS": {
        "title": "Optimization Delta Table",
        "business_question": "Is the recommended allocation materially better than current?",
        "kpi_name": "Current vs Optimized Metrics",
    },
    "TAB_SIMULATOR_OPTIMIZATION_METRICS": {
        "title": "Simulator Outcome Metrics",
        "business_question": "Do manual assumptions preserve value uplift?",
        "kpi_name": "Simulated Outcome Delta",
    },
    "TAB_INSIGHTS_CHANNEL_PERFORMANCE_TABLE": {
        "title": "Ranked Channel Performance",
        "business_question": "Which channels are best after confidence-adjustment?",
        "kpi_name": "ROI / CI / Confidence",
    },
    "TAB_SETTINGS_ONE_PAGER_METRIC_CARDS": {
        "title": "Model Quality One-Pager",
        "business_question": "Is this model fit for operational use?",
        "kpi_name": "R² / MAPE / Fit Signals",
    },
}

REQUIRED_SEMANTIC_FIELDS = [
    "component_id",
    "tab_business_purpose",
    "why_this_exists",
    "kpi_or_chart_definition",
    "formula",
    "inputs",
    "unit_and_scale",
    "how_to_read_good_vs_risk",
    "decision_supported",
    "recommended_next_action",
    "misinterpretation_risks",
    "data_freshness_or_caveats",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build business dashboard docs")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to component manifest (defaults to <run-dir>/manifests/component_manifest.json)",
    )
    parser.add_argument(
        "--callout-spec",
        default="/Users/amank/Code/marketing-mix/temp/dashboard-docs/spec/callouts.json",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def ensure_run_layout(run_dir: Path) -> None:
    for folder in ["clean", "annotated", "manifests", "docs", "logs"]:
        (run_dir / folder).mkdir(parents=True, exist_ok=True)


def build_callouts(captures: list[dict[str, Any]], spec_path: Path) -> dict[str, list[dict[str, Any]]]:
    callouts: list[dict[str, Any]] = []
    by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for idx, capture in enumerate(captures, start=1):
        section = capture["section"]
        template = SECTION_TEMPLATE.get(section, SECTION_TEMPLATE["tab-overview"])
        override = CALL_OUT_OVERRIDES.get(capture["component_id"], {})
        callout = {
            "callout_id": f"CO_{idx:03d}",
            "component_id": capture["component_id"],
            "label_number": 1,
            "selector_or_bbox": {
                "bbox": template["bbox"],
                "strategy": "heuristic_bbox",
            },
            "title": override.get("title", template["title"]),
            "business_question": override.get("business_question", template["business_question"]),
            "kpi_name": override.get("kpi_name", template["kpi_name"]),
            "screenshot": capture["screenshot"],
        }
        callouts.append(callout)
        by_image[capture["screenshot"]].append(callout)

    spec = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "description": "Heuristic callout map for business-first dashboard documentation.",
        "fields": [
            "callout_id",
            "component_id",
            "label_number",
            "selector_or_bbox",
            "title",
            "business_question",
            "kpi_name",
            "screenshot",
        ],
        "callouts": callouts,
    }
    write_json(spec_path, spec)
    return by_image


def _draw_number(draw: ImageDraw.ImageDraw, x: int, y: int, label: str) -> None:
    radius = 18
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(219, 39, 119, 230), outline=(255, 255, 255, 255), width=2)
    font = ImageFont.load_default()
    draw.text((x - 6, y - 6), label, fill=(255, 255, 255, 255), font=font)


def annotate_image(src: Path, dst: Path, callouts: list[dict[str, Any]]) -> None:
    image = Image.open(src).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")

    for callout in callouts:
        x, y, w, h = callout["selector_or_bbox"]["bbox"]
        x2, y2 = x + w, y + h

        draw.rectangle((x, y, x2, y2), outline=(219, 39, 119, 230), width=4)

        label_x = x - 32 if x > 120 else min(x2 + 32, image.width - 30)
        label_y = max(28, y - 26)
        draw.line((x, y, label_x, label_y), fill=(219, 39, 119, 230), width=3)
        _draw_number(draw, int(label_x), int(label_y), str(callout["label_number"]))

    dst.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(dst, format="PNG")


def build_callout_manifest(
    captures: list[dict[str, Any]],
    callouts_by_image: dict[str, list[dict[str, Any]]],
    run_dir: Path,
) -> dict[str, Any]:
    annotated_dir = run_dir / "annotated"
    items: list[dict[str, Any]] = []

    for capture in captures:
        src = Path(capture["screenshot"])
        image_callouts = callouts_by_image.get(capture["screenshot"], [])
        dst = annotated_dir / src.name
        annotate_image(src, dst, image_callouts)
        items.append(
            {
                "component_id": capture["component_id"],
                "tab": capture["tab"],
                "state": capture["state"],
                "section": capture["section"],
                "clean_screenshot": str(src),
                "annotated_screenshot": str(dst),
                "callouts": image_callouts,
            }
        )

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "run_dir": str(run_dir),
        "items": items,
        "annotated_count": len(items),
        "callout_count": sum(len(it["callouts"]) for it in items),
    }


def build_semantics(captures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for capture in captures:
        section = capture["section"]
        template = SECTION_TEMPLATE.get(section, SECTION_TEMPLATE["tab-overview"])

        semantic = {
            "component_id": capture["component_id"],
            "tab_business_purpose": TAB_PURPOSE.get(capture["tab"], "Support evidence-based budget decisions."),
            "why_this_exists": template["business_question"],
            "kpi_or_chart_definition": template["kpi_or_chart_definition"],
            "formula": template["formula"],
            "inputs": template["inputs"],
            "unit_and_scale": template["unit_and_scale"],
            "how_to_read_good_vs_risk": template["how_to_read_good_vs_risk"],
            "decision_supported": template["decision_supported"],
            "recommended_next_action": template["recommended_next_action"],
            "misinterpretation_risks": template["misinterpretation_risks"],
            "data_freshness_or_caveats": template["data_freshness_or_caveats"],
            "worked_example": CRITICAL_WORKED_EXAMPLES.get(capture["component_id"], "N/A"),
        }
        out[capture["component_id"]] = semantic
    return out


def rel_to_docs(path: Path, docs_dir: Path) -> str:
    return os.path.relpath(path, docs_dir).replace("\\", "/")


def markdown_link_checks(path: Path, docs_dir: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    missing = [r for r in refs if not (docs_dir / r).exists()]
    return len(refs), len(missing)


def html_link_checks(path: Path, docs_dir: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    refs = re.findall(r'src="([^"]+\.png)"', text)
    missing = [r for r in refs if not (docs_dir / r).exists()]
    return len(refs), len(missing)


def generate_markdown(
    run_dir: Path,
    component_manifest: dict[str, Any],
    callout_manifest: dict[str, Any],
    semantics_by_component: dict[str, dict[str, Any]],
) -> str:
    captures = component_manifest["captures"]
    by_tab: dict[str, list[dict[str, Any]]] = defaultdict(list)
    callouts_by_component = {x["component_id"]: x for x in callout_manifest["items"]}

    for cap in captures:
        by_tab[cap["tab"]].append(cap)

    for tab in by_tab:
        by_tab[tab].sort(key=lambda c: c["screenshot"])

    docs_dir = run_dir / "docs"
    generated_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    ctx = component_manifest["canonical_context"]

    lines: list[str] = []
    lines.append("# Dashboard Business Reference")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(
        "This reference explains each dashboard tab in business language: what it means, how to read each KPI/chart, and which decision it supports. "
        "Every section includes explicit formulas to keep interpretation transparent."
    )
    lines.append("")
    lines.append("## Run Context")
    lines.append(f"- Generated: `{generated_at}`")
    lines.append(
        f"- Canonical selection: `{ctx['country']} / {ctx['product']} / {ctx['year']} / {ctx['version']} / {ctx['data_source']}`"
    )
    lines.append(f"- Screenshots captured: `{component_manifest['screenshot_count']}`")
    lines.append(f"- Annotated screenshots: `{callout_manifest['annotated_count']}`")
    lines.append("")

    lines.append("## How To Use The Dashboard In Decision Flow")
    for tab in TAB_ORDER:
        lines.append(f"1. **{TAB_TITLE[tab]}**: {TAB_DECISIONS[tab]}")
    lines.append("")

    lines.append("## Tab-by-Tab Business Explanation")

    for tab in TAB_ORDER:
        items = by_tab.get(tab, [])
        if not items:
            continue
        lines.append("")
        lines.append(f"### {TAB_TITLE[tab]} (`{tab}`)")
        lines.append("")
        lines.append(f"- **Tab purpose**: {TAB_PURPOSE[tab]}")
        lines.append(f"- **Primary decision enabled**: {TAB_DECISIONS[tab]}")
        lines.append("")

        for cap in items:
            cid = cap["component_id"]
            sem = semantics_by_component[cid]
            citem = callouts_by_component[cid]
            ann_rel = rel_to_docs(Path(citem["annotated_screenshot"]), docs_dir)
            lines.append(f"#### `{cid}`")
            lines.append("")
            lines.append(f"- **Business purpose**: {sem['tab_business_purpose']}")
            lines.append(f"- **Why this exists**: {sem['why_this_exists']}")
            lines.append(f"- **KPI/Chart meaning**: {sem['kpi_or_chart_definition']}")
            lines.append(f"- **Formula**: `{sem['formula']}`")
            lines.append(f"- **Inputs**: `{', '.join(sem['inputs'])}`")
            lines.append(f"- **Unit/Scale**: {sem['unit_and_scale']}")
            lines.append(f"- **How to read (good vs risk)**: {sem['how_to_read_good_vs_risk']}")
            lines.append(f"- **Decision supported**: {sem['decision_supported']}")
            lines.append(f"- **Recommended next action**: {sem['recommended_next_action']}")
            lines.append(f"- **Misinterpretation risk**: {sem['misinterpretation_risks']}")
            lines.append(f"- **Data caveat**: {sem['data_freshness_or_caveats']}")
            if sem["worked_example"] != "N/A":
                lines.append(f"- **Worked example**: {sem['worked_example']}")
            lines.append("")
            lines.append(f"![{cid}]({ann_rel})")
            lines.append("")
            lines.append("| # | Callout Title | Business Question | KPI Name |")
            lines.append("|---|---|---|---|")
            for callout in citem["callouts"]:
                lines.append(
                    f"| {callout['label_number']} | {callout['title']} | {callout['business_question']} | {callout['kpi_name']} |"
                )
            lines.append("")

    lines.append("## KPI And Graph Playbook")
    seen: set[str] = set()
    for cap in captures:
        sem = semantics_by_component[cap["component_id"]]
        kpi = SECTION_TEMPLATE.get(cap["section"], SECTION_TEMPLATE["tab-overview"])["kpi_name"]
        key = f"{kpi}|{sem['formula']}|{sem['recommended_next_action']}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- **{kpi}**: `{sem['formula']}` | Action: {sem['recommended_next_action']}")

    lines.append("")
    lines.append("## Glossary")
    lines.append("- **Incremental Sales**: Modeled sales lift attributed to media and controllable drivers.")
    lines.append("- **ROI / ROAS**: Efficiency ratio between incremental outcome and spend.")
    lines.append("- **mROI**: Marginal return of the next spend increment, not average return.")
    lines.append("- **Saturation**: How close a channel is to diminishing-return ceiling.")
    lines.append("- **Trust Score**: Confidence proxy from diagnostics and uncertainty quality.")
    lines.append("")

    lines.append("## Caveats")
    lines.append("- Formulas are transparent, but many metrics are model-based estimates rather than direct causal certainties.")
    lines.append("- Always validate large reallocation steps with scenario stress-testing before operational rollout.")
    lines.append("- Territory analytics requires advanced tier and relevant artifacts.")
    lines.append("")
    return "\n".join(lines)


def generate_html(
    run_dir: Path,
    component_manifest: dict[str, Any],
    callout_manifest: dict[str, Any],
    semantics_by_component: dict[str, dict[str, Any]],
) -> str:
    captures = component_manifest["captures"]
    by_tab: dict[str, list[dict[str, Any]]] = defaultdict(list)
    callouts_by_component = {x["component_id"]: x for x in callout_manifest["items"]}

    for cap in captures:
        by_tab[cap["tab"]].append(cap)
    for tab in by_tab:
        by_tab[tab].sort(key=lambda c: c["screenshot"])

    docs_dir = run_dir / "docs"

    nav = []
    content = []

    for tab in TAB_ORDER:
        items = by_tab.get(tab, [])
        if not items:
            continue

        tab_anchor = tab
        nav.append(f'<li><a href="#{tab_anchor}">{html.escape(TAB_TITLE[tab])}</a></li>')

        cards = []
        for cap in items:
            cid = cap["component_id"]
            sem = semantics_by_component[cid]
            citem = callouts_by_component[cid]
            ann_rel = rel_to_docs(Path(citem["annotated_screenshot"]), docs_dir)
            rows = "".join(
                f"<tr><td>{co['label_number']}</td><td>{html.escape(co['title'])}</td><td>{html.escape(co['business_question'])}</td><td>{html.escape(co['kpi_name'])}</td></tr>"
                for co in citem["callouts"]
            )

            cards.append(
                f"""
                <article class=\"card\" id=\"{cid}\">
                  <h4>{html.escape(cid)}</h4>
                  <p><b>Business purpose:</b> {html.escape(sem['tab_business_purpose'])}</p>
                  <p><b>Why this exists:</b> {html.escape(sem['why_this_exists'])}</p>
                  <p><b>KPI/Chart meaning:</b> {html.escape(sem['kpi_or_chart_definition'])}</p>
                  <p><b>Formula:</b> <code>{html.escape(sem['formula'])}</code></p>
                  <p><b>Inputs:</b> <code>{html.escape(', '.join(sem['inputs']))}</code></p>
                  <p><b>How to read:</b> {html.escape(sem['how_to_read_good_vs_risk'])}</p>
                  <p><b>Decision supported:</b> {html.escape(sem['decision_supported'])}</p>
                  <p><b>Recommended action:</b> {html.escape(sem['recommended_next_action'])}</p>
                  <p><b>Risk:</b> {html.escape(sem['misinterpretation_risks'])}</p>
                  <p><b>Caveat:</b> {html.escape(sem['data_freshness_or_caveats'])}</p>
                  {f"<p><b>Worked example:</b> {html.escape(sem['worked_example'])}</p>" if sem['worked_example'] != 'N/A' else ''}
                  <img src=\"{html.escape(ann_rel)}\" alt=\"{html.escape(cid)}\" loading=\"lazy\" />
                  <table>
                    <thead><tr><th>#</th><th>Callout</th><th>Business Question</th><th>KPI</th></tr></thead>
                    <tbody>{rows}</tbody>
                  </table>
                </article>
                """
            )

        content.append(
            f"""
            <section class=\"tab\" id=\"{tab_anchor}\">
              <h3>{html.escape(TAB_TITLE[tab])}</h3>
              <p><b>Tab purpose:</b> {html.escape(TAB_PURPOSE[tab])}</p>
              <p><b>Primary decision:</b> {html.escape(TAB_DECISIONS[tab])}</p>
              {''.join(cards)}
            </section>
            """
        )

    generated_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Dashboard Business Reference</title>
  <style>
    :root {{ --bg:#f7f7f2; --ink:#1a1d20; --muted:#5d6369; --line:#d7dbdf; --card:#ffffff; --accent:#db2777; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; color:var(--ink); background:linear-gradient(160deg,#f7f7f2,#eef4f8); }}
    .layout {{ display:grid; grid-template-columns: 280px 1fr; min-height:100vh; }}
    aside {{ border-right:1px solid var(--line); padding:20px; position:sticky; top:0; height:100vh; overflow:auto; background:rgba(255,255,255,0.85); backdrop-filter: blur(6px); }}
    main {{ padding:24px; max-width:1300px; }}
    h1 {{ margin-top:0; }}
    h3 {{ margin-top:36px; }}
    .meta {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
    ul {{ margin:0; padding-left:18px; }}
    li {{ margin:8px 0; }}
    a {{ color:#0f5f9e; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; margin:16px 0; box-shadow:0 8px 24px rgba(0,0,0,0.05); }}
    .card img {{ width:100%; height:auto; border-radius:12px; border:1px solid var(--line); margin:10px 0; }}
    code {{ background:#f5f5f5; border:1px solid #ececec; border-radius:6px; padding:1px 6px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:14px; }}
    th,td {{ border:1px solid var(--line); padding:8px; text-align:left; vertical-align:top; }}
    th {{ background:#f3f6f9; }}
    @media (max-width: 980px) {{
      .layout {{ grid-template-columns: 1fr; }}
      aside {{ position:relative; height:auto; border-right:none; border-bottom:1px solid var(--line); }}
      main {{ padding:16px; }}
    }}
  </style>
</head>
<body>
  <div class=\"layout\">
    <aside>
      <h2>Dashboard Guide</h2>
      <div class=\"meta\">Generated {generated_at}</div>
      <ul>{''.join(nav)}</ul>
    </aside>
    <main>
      <h1>Business-First Dashboard Reference</h1>
      <p class=\"meta\">Focus: business meaning, KPI formulas, and action guidance.</p>
      {''.join(content)}
    </main>
  </div>
</body>
</html>
"""


def qa_report(
    run_dir: Path,
    component_manifest: dict[str, Any],
    callout_manifest: dict[str, Any],
    semantics_by_component: dict[str, dict[str, Any]],
    md_path: Path,
    html_path: Path,
) -> dict[str, Any]:
    captures = component_manifest["captures"]

    tabs_present = sorted({c["tab"] for c in captures})
    coverage_ok = set(TAB_ORDER).issubset(set(tabs_present))

    per_tab_sections: dict[str, set[str]] = defaultdict(set)
    for c in captures:
        per_tab_sections[c["tab"]].add(c["section"])

    missing_required: dict[str, list[str]] = {}
    for tab, req in REQUIRED_SECTIONS.items():
        missing = sorted(req - per_tab_sections.get(tab, set()))
        if missing:
            missing_required[tab] = missing

    callout_missing = [it["component_id"] for it in callout_manifest["items"] if len(it["callouts"]) == 0]

    incomplete_components: list[dict[str, Any]] = []
    for component_id, sem in semantics_by_component.items():
        missing = [field for field in REQUIRED_SEMANTIC_FIELDS if not sem.get(field)]
        if missing:
            incomplete_components.append({"component_id": component_id, "missing_fields": missing})

    md_refs, md_missing = markdown_link_checks(md_path, run_dir / "docs")
    html_refs, html_missing = html_link_checks(html_path, run_dir / "docs")

    status_outside_temp = subprocess.run(
        ["/bin/zsh", "-lc", "git -C /Users/amank/Code/marketing-mix status --short"],
        capture_output=True,
        text=True,
        check=False,
    )
    bad_paths: list[str] = []
    for line in status_outside_temp.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        path = parts[-1] if parts else ""
        if not path:
            continue
        if path.startswith("temp/"):
            continue
        if path in {
            "apps/dashboard/package.json",
            "apps/dashboard/package-lock.json",
        }:
            continue
        # Pre-existing user files can stay modified; this hygiene check is for doc-pipeline pollution.
        if path.startswith("docs/DASHBOARD_COMPONENT_REFERENCE"):
            bad_paths.append(path)
        if path.startswith("docs/assets/dashboard-component-reference"):
            bad_paths.append(path)
        if path.startswith("scripts/build_dashboard_component_docs.py"):
            bad_paths.append(path)
        if path.startswith("scripts/capture_dashboard_component_reference_playwright.mjs"):
            bad_paths.append(path)
        if path.startswith("apps/dashboard/scripts"):
            bad_paths.append(path)

    checks = {
        "tab_coverage": {
            "ok": coverage_ok,
            "tabs_present": tabs_present,
            "required_tabs": TAB_ORDER,
        },
        "required_section_coverage": {
            "ok": len(missing_required) == 0,
            "missing": missing_required,
        },
        "callout_coverage": {
            "ok": len(callout_missing) == 0,
            "components_without_callouts": callout_missing,
        },
        "business_semantics_completeness": {
            "ok": len(incomplete_components) == 0,
            "incomplete_components": incomplete_components,
        },
        "markdown_links": {"ok": md_missing == 0, "refs": md_refs, "missing": md_missing},
        "html_links": {"ok": html_missing == 0, "refs": html_refs, "missing": html_missing},
        "hygiene_outside_temp": {
            "ok": len(bad_paths) == 0,
            "bad_paths": sorted(set(bad_paths)),
        },
    }

    all_ok = all(v["ok"] for v in checks.values())

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "run_dir": str(run_dir),
        "all_checks_passed": all_ok,
        "checks": checks,
        "counts": {
            "captures": len(captures),
            "annotated": callout_manifest["annotated_count"],
            "callouts": callout_manifest["callout_count"],
            "semantics_rows": len(semantics_by_component),
        },
    }


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    ensure_run_layout(run_dir)

    manifest_path = Path(args.manifest).resolve() if args.manifest else run_dir / "manifests" / "component_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    component_manifest = read_json(manifest_path)
    captures = component_manifest.get("captures", [])
    if not captures:
        raise SystemExit("Capture manifest has no captures.")

    spec_path = Path(args.callout_spec).resolve()
    callouts_by_image = build_callouts(captures, spec_path)

    callout_manifest = build_callout_manifest(captures, callouts_by_image, run_dir)
    callout_manifest_path = run_dir / "manifests" / "callout_manifest.json"
    write_json(callout_manifest_path, callout_manifest)

    semantics_by_component = build_semantics(captures)
    business_semantics_path = run_dir / "manifests" / "business_semantics.json"
    write_json(
        business_semantics_path,
        {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "rows": [semantics_by_component[c["component_id"]] for c in captures],
        },
    )

    md = generate_markdown(run_dir, component_manifest, callout_manifest, semantics_by_component)
    md_path = run_dir / "docs" / "DASHBOARD_BUSINESS_REFERENCE.md"
    md_path.write_text(md, encoding="utf-8")

    html_doc = generate_html(run_dir, component_manifest, callout_manifest, semantics_by_component)
    html_path = run_dir / "docs" / "DASHBOARD_BUSINESS_REFERENCE.html"
    html_path.write_text(html_doc, encoding="utf-8")

    report = qa_report(run_dir, component_manifest, callout_manifest, semantics_by_component, md_path, html_path)
    report_path = run_dir / "manifests" / "qa_report.json"
    write_json(report_path, report)

    log_lines = [
        f"Run dir: {run_dir}",
        f"Component manifest: {manifest_path}",
        f"Callout spec: {spec_path}",
        f"Callout manifest: {callout_manifest_path}",
        f"Business semantics: {business_semantics_path}",
        f"Markdown: {md_path}",
        f"HTML: {html_path}",
        f"QA report: {report_path}",
        f"All checks passed: {report['all_checks_passed']}",
    ]
    (run_dir / "logs" / "build.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print("\n".join(log_lines))


if __name__ == "__main__":
    main()
