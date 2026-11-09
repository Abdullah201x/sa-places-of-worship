---
name: Manara Geospatial Portal
description: Design system for the Saudi Places of Worship Map and OSM Data Quality Workspace
colors:
  primary: "#00f2fe"
  secondary: "#4facfe"
  accent: "#00ff87"
  warn: "#ffb03a"
  danger: "#ff453a"
  text-primary: "#f1f5f9"
  text-muted: "#94a3b8"
  bg-dark: "#0a0b10"
  panel-bg: "rgba(13, 15, 23, 0.75)"
  panel-border: "rgba(255, 255, 255, 0.08)"
typography:
  display:
    fontFamily: "Cairo Variable, system-ui, -apple-system, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.2
  headline:
    fontFamily: "Cairo Variable, system-ui, -apple-system, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Cairo Variable, system-ui, -apple-system, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.bg-dark}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  card-panel:
    backgroundColor: "{colors.panel-bg}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
    padding: "16px"
---

# Design System

## Overview
Manara is a focused dark-mode geospatial dashboard and GIS editing portal designed for high information density, cartographic visual hierarchy, and full Arabic (RTL) and Latin bilingual legibility.

## Colors
The palette leverages a deep cosmos dark slate background (`#0a0b10`) to allow map vector data, satellite imagery, and spatial anomalies to stand out clearly.
- **Primary (`#00f2fe`):** Interactive focal points, active controls, and primary callouts.
- **Secondary (`#4facfe`):** Supporting navigation accents and intermediate data states.
- **Accent (`#00ff87`):** Validated data points, successful actions, and positive quality marks.
- **Warn (`#ffb03a`):** Potential anomalies, missing names, and moderate Qibla deviations.
- **Danger (`#ff453a`):** Severe geometry distortion, unverified duplicates, and critical gaps.
- **Neutrals:** Text primary `#f1f5f9` (contrast ratio > 12:1 against dark backgrounds) and secondary muted `#94a3b8` (contrast ratio > 5.5:1 against dark backgrounds).

## Typography
Manara relies on the self-hosted **Cairo Variable** font family across Arabic and Latin scripts.
- **Display & Headlines:** Weight 600-700 with clear size steps (24px, 20px, 18px) to establish distinct visual hierarchy.
- **Body:** 15px (0.9375rem) with 1.5 line height for optimal Arabic reading comfort.
- **Monospace:** Reserved for coordinates, OSM node/way IDs, and bounding box coordinates.

## Layout
- **Full Viewport Shell:** Map takes primary viewport estate with a collapsible side-panel (420px max-width) and unobtrusive floating top toolbar.
- **RTL-First Symmetry:** Layout directions, padding, and alignments utilize CSS logical properties (`margin-inline`, `padding-inline`, `inset-inline-start`) to switch cleanly between Arabic (RTL) and English (LTR).

## Elevation & Depth
- **Panel Depth:** Translucent dark panels with subtle backdrop blur (`16px`) and delicate border definition (`rgba(255, 255, 255, 0.08)`).
- **Shadows:** Soft diffuse shadows (`0 10px 30px -5px rgba(0, 0, 0, 0.5)`) providing tactile separation above the interactive map without heavy halos or harsh drop-shadows.

## Shapes
- **Radius Scale:** Refined rounding tokens (`rounded-sm: 4px`, `rounded-md: 8px`, `rounded-lg: 12px`).
- **Control Forms:** Floating action buttons and pill badges use full rounding (`9999px`) for quick visual scanning against angular card containers.

## Components
- **Detail Cards:** Transparent panels with clean interior borders and structured meta-rows. Avoid arbitrary thick left/right stripes.
- **KPI Badges:** Clean numerical readouts with muted descriptive subtitles; avoid decorative text gradients.
- **Interactive Modals:** Centered overlay dialogs with explicit keyboard focus-visible rings and backdrop dismissal.

## Do's and Don'ts
- **DO** use CSS logical properties (`padding-inline`, `border-inline-start`) for RTL compatibility.
- **DO** verify WCAG AA contrast (≥ 4.5:1 for body text, ≥ 3:1 for large graphical accents).
- **DO** use exponential easing (`ease-out-cubic` / `ease-out-quart`) for smooth panel slides and tooltips.
- **DON'T** use thick side-border stripes (side-tabs) on cards as an arbitrary accent.
- **DON'T** use `background-clip: text` gradient fills on headers, labels, or numbers.
- **DON'T** use bounce or elastic cubic-bezier easing in data or map transitions.
