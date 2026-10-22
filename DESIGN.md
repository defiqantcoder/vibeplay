---
name: Studio Telemetry
colors:
  surface: '#101224'
  surface-dim: '#101224'
  surface-bright: '#36384c'
  surface-container-lowest: '#0b0d1f'
  surface-container-low: '#181a2d'
  surface-container: '#1c1e31'
  surface-container-high: '#27293c'
  surface-container-highest: '#313347'
  on-surface: '#e0e0fa'
  on-surface-variant: '#c6c5d0'
  inverse-surface: '#e0e0fa'
  inverse-on-surface: '#2d2f42'
  outline: '#90909a'
  outline-variant: '#45464f'
  surface-tint: '#b8c4fb'
  primary: '#b8c4fb'
  on-primary: '#212d5b'
  primary-container: '#6874a6'
  on-primary-container: '#ffffff'
  inverse-primary: '#505c8c'
  secondary: '#ffb2bd'
  on-secondary: '#650425'
  secondary-container: '#84203b'
  on-secondary-container: '#ff97a9'
  tertiary: '#e3c375'
  on-tertiary: '#3e2e00'
  tertiary-container: '#8d732e'
  on-tertiary-container: '#ffffff'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#dce1ff'
  primary-fixed-dim: '#b8c4fb'
  on-primary-fixed: '#091845'
  on-primary-fixed-variant: '#384473'
  secondary-fixed: '#ffd9de'
  secondary-fixed-dim: '#ffb2bd'
  on-secondary-fixed: '#400014'
  on-secondary-fixed-variant: '#84203b'
  tertiary-fixed: '#ffdf94'
  tertiary-fixed-dim: '#e3c375'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#594400'
  background: '#101224'
  on-background: '#e0e0fa'
  surface-variant: '#313347'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: -0.005em
  body-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  body-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.04em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '500'
    lineHeight: 12px
    letterSpacing: 0.06em
  telemetry-counter:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.5rem
  gutter-compact: 0.25rem
  margin: 0.75rem
  space-xs: 0.125rem
  space-sm: 0.25rem
  space-md: 0.5rem
  space-lg: 0.75rem
  space-xl: 1rem
---

## Brand & Style

This design system delivers a high-precision, utilitarian studio workstation environment tailored for audiophile desktop engines, mastering suites, and digital signal processors. The aesthetic merges clinical geometric layouts with dense monospace readouts, establishing a focused, distraction-free environment for professional audio engineers and technical operators.

### Visual Style
- **Aesthetic Movement:** Utilitarian Studio Standard. High-density, instrumented desktop interface governed by hairline structural borders, muted slate surfaces, and targeted signal accents.
- **Personality:** Analytical, uncompromising, calibrated, and quiet.
- **Emotional Intent:** Instill confidence through deterministic feedback, microscopic parameter control, and physical rack-mount clarity translated into native desktop software.

## Colors

The palette operates under the strict "God of Ink" dark specification, prioritizing contrast preservation for sustained low-light monitoring sessions without eye strain.

- **Canvas (`#181824`):** The foundational substrate of the desktop shell, title bars, and background wells.
- **Surface Panels (`#232538`):** Applied to parameter cards, channel strips, rack modules, and inspector bays.
- **Structural Lines (`#383B56`):** Precision 1px dividers, gridlines, and hairline bounding boxes establishing optical structure without bulk.
- **Signal Indigo / Primary (`#6874A6`):** The primary focus state and active telemetry vector. Used for active tabs, selected states, scrubbers, and engaged routing paths.
- **Crimson Clip / Secondary (`#801D38`):** Telemetry warning, clip indicators, mute indicators, and peak threshold badges.
- **Typography Scale:** `#EBEFF8` handles high-legibility primary readout metrics and titles; `#9CA3AF` maps to passive metadata, labels, and channel unit demarcations.

## Typography

The type system implements a dual-engine model:
1. **Inter** governs functional structural headlines, modal framing, and window-level UI chrome to ensure immediate spatial legibility.
2. **JetBrains Mono** governs all parameter values, telemetry counters, axis steps, status codes, and input labels.

All monospace values must be rendered with tabular lining figures enabled (`font-variant-numeric: tabular-nums`) to prevent horizontal jittering during rapid audio buffer updates and VU meter streaming. All micro-labels (`label-sm`, `label-md`) must be styled uppercase with tracking to maintain legible definition against dark surfaces.

## Layout & Spacing

Designed specifically for dense, multi-pane desktop workstations operating across 1080p, 1440p, and 4K native displays. 

- **Layout Structure:** Multi-split panel layout composed of persistent navigation ribbons, modular inspector decks, mixer matrices, and central audio waveform/DSP viewports.
- **Rhythm & Grid:** Built on an absolute 4px baseline (`0.25rem`). Standard layout gutters sit at `0.5rem` (8px), shrinking to `0.25rem` (4px) inside rack units to maximize real estate for high-density parameter controls.
- **Canvas Margins:** Fixed `0.75rem` (12px) outer frame borders from the desktop window edges, supporting frameless custom title bars and hardware-accelerated viewport docks.

## Elevation & Depth

This system intentionally rejects diffused shadows and skeuomorphic gradients in favor of **Tonal Layering & Precision Outlines**.

- **Depth Planes:**
  - `Level 0 (Canvas Base)`: `#181824` — window background and master chassis.
  - `Level 1 (Dock & Rack Surfaces)`: `#232538` — parameter bays, audio cards, and table headers.
  - `Level 2 (In-Rack Controls & Wells)`: `#1D1E2C` (10% darker tonal inset) — nested input fields, fader tracks, and spectrum analyzer wells.
  - `Level 3 (Overlay Heads-Up Panels)`: `#2A2D42` with 1px border `#6874A6` — floating plugin inspectors, context menus, and tooltips.
- **Borders & Dividers:** Visual hierarchy is enforced entirely by 1px hairline borders (`#383B56`). Elevated items use a crisp 1px stroke of `#6874A6` at 40% opacity rather than drop shadows.

## Shapes

The interface embraces an engineered, architectural curvature:
- **Roundedness Factor (1):** Standard modules, buttons, and inputs strictly adhere to `0.25rem` (4px) corner radii.
- **Sub-components:** Mini chips, counter tags, and step-sequencer pads use a subtle `0.125rem` (2px) radius to maintain crisp rectangular geometry when rendered adjacent to each other.
- **Floating Modals & Flyouts:** Retain a uniform `0.25rem` (4px) radius bounded by structural `#383B56` borders. Full pill shapes are forbidden to preserve technical modularity.

## Components

### Buttons & Transport Triggers
- **Primary Action (Active Tab / Armed Engine):** Background `#6874A6`, text `#EBEFF8`, 1px border `#6874A6`. Hover advances brightness by 8%; active press triggers 1px internal inset.
- **Secondary / Utility Button:** Background `#232538`, text `#EBEFF8`, 1px border `#383B56`.
- **Destructive / Peak Alert Button (Clip / Mute):** Background `#801D38`, text `#EBEFF8`, border `#801D38`.
- **Dimensions:** Compact 24px and 28px standard heights with `space-md` horizontal padding.

### Chips, Tags & Badges
- **Telemetry Readout Chip:** Background `#181824`, border 1px `#383B56`, text `#9CA3AF`, mono numeric text in `#EBEFF8`.
- **Status / Warning Tag:** 1px solid `#801D38` stroke, transparent or 15% tinted crimson background, uppercase `label-sm`.

### Channel Lists & Parameter Tables
- **Table Rows:** Compact height (24px to 28px). Hover state tints background to `#2A2D42`. Selected state applies a 2px left border accent in `#6874A6` with `#232538` fill.
- **Dividers:** 1px hairline horizontal divider in `#383B56`.

### Checkboxes & Segmented Toggles
- **Box Frame:** 14x14px square, `0.125rem` radius, 1px border `#383B56`.
- **Checked State:** Fill `#6874A6` with an inner solid tick in `#EBEFF8`.
- **Segmented Toggle Group:** Enclosed within a `#181824` container; active segment elevated with `#232538` and a 1px border of `#6874A6`.

### Inputs & Numeric Steppers
- **Field Structure:** Background `#181824`, 1px border `#383B56`, text `#EBEFF8`. Height 24px.
- **Focus State:** 1px crisp stroke of `#6874A6`. No glow rings.
- **Inline Stepper:** Monospaced values with integrated right-hand increment/decrement arrows aligned directly within the border container.

### Module Cards & Rack Shells
- **Panel Surface:** Background `#232538`, 1px border `#383B56`, 4px corner radius.
- **Card Header:** 28px fixed height bar with an integrated drag handle grip, mono title in `#EBEFF8`, and a bottom border of 1px `#383B56`.

### Telemetry Displays & VU Strips
- **Meter Rails:** 4px to 6px wide vertical or horizontal troughs in `#181824`. Active audio range marked by solid `#6874A6` blocks transitioning immediately to `#801D38` at -0.1 dBFS.