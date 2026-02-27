# Sonarr-Style Dark Sidebar UI Redesign

**Date:** 2026-02-26
**Status:** Approved

## Goal

Restyle the app to match Sonarr's visual language: dark grey background, light grey text, left sidebar navigation, purple link hovers, compact typography.

## Approach

CSS-only retheme. Keep Pico CSS as the foundation, override to dark-first defaults, restructure `base.html` for a sidebar layout.

## Layout

```
Desktop (>768px):                       Mobile (<=768px):
┌──────────┬─────────────────────┐     ┌────┬──────────────────────┐
│ [icon]   │ (content)           │     │ ◉  │ (content)            │
│ Splintarr│                     │     │ ◎  │                      │
│──────────│                     │     │ ☰  │                      │
│▶Dashboard│                     │     │ ◷  │                      │
│ Instances│                     │     │    │                      │
│ Queues   │                     │     │ ⚙  │                      │
│ History  │                     │     │ ⏻  │                      │
│          │                     │     └────┴──────────────────────┘
│ Settings │                     │
│ Logout   │                     │     Sidebar: 60px, icon-only
└──────────┴─────────────────────┘
Sidebar: 240px
```

- CSS Grid: `grid-template-columns: 240px 1fr` (desktop), `60px 1fr` (mobile)
- Sidebar: fixed position, full viewport height, scrollable if needed
- Content: scrollable independently, max-width unconstrained (fluid)
- Login/setup pages: no sidebar, centered dark layout

## Color Scheme

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-body` | `#1a1d23` | Page background |
| `--bg-sidebar` | `#15171c` | Sidebar background |
| `--bg-card` | `#252832` | Cards, articles, table rows |
| `--bg-card-alt` | `#1a1d23` | Alternating table rows |
| `--text-primary` | `#d1d5db` | Default body text |
| `--text-muted` | `#9ca3af` | Secondary text, labels |
| `--text-heading` | `#f3f4f6` | Headings |
| `--border-color` | `#383d45` | Card borders, dividers |
| `--link-color` | `#d1d5db` | Links (same as text) |
| `--link-hover` | `#9333ea` | Link hover (purple) |
| `--nav-active-border` | `#9333ea` | Active nav item left border |
| `--nav-active-text` | `#9333ea` | Active nav item text |
| `--brand-primary` | `#9333ea` | Buttons, accents (unchanged) |
| `--brand-success` | `#48c774` | Healthy status (unchanged) |
| `--brand-danger` | `#ff5555` | Failed status (unchanged) |
| `--brand-warning` | `#ffb86c` | Warning (unchanged) |

## Typography

| Element | Current | New |
|---------|---------|-----|
| Base font-size | 16px | 14px |
| h1 | 2.25rem | 1.5rem |
| h2 | 1.875rem | 1.25rem |
| h3 | 1.5rem | 1.1rem |
| h4 | 1.25rem | 1rem |
| Line-height | 1.6 | 1.5 |
| Nav links | inherited | 14px, weight 500 |

## Sidebar Navigation

Items with Unicode icons (no icon library dependency):

| Icon | Label | Route | Notes |
|------|-------|-------|-------|
| ◉ | Dashboard | /dashboard | |
| ◎ | Instances | /dashboard/instances | |
| ☰ | Queues | /dashboard/search-queues | |
| ◷ | History | /dashboard/search-history | |
| ⚙ | Settings | /dashboard/settings | Bottom section |
| ⏻ | Logout | JS action | Bottom section |

Active page indicated by: left 3px purple border + purple text color.

## Files to Change

1. **`base.html`** — Restructure layout: `<div class="app-layout">` with `<aside class="sidebar">` + `<div class="main-content">`. Conditional sidebar (only when authenticated).
2. **`sonarr-theme.css`** — Rewrite color variables to dark-first defaults (remove `[data-theme="dark"]` block, make dark the default). Add sidebar styles, update typography scale.
3. **`custom.css`** — Update nav styles from horizontal to sidebar. Adjust card, table, form styles for dark background.
4. **Login/setup templates** — Add `data-no-sidebar` or use a block override to suppress sidebar. Ensure dark background with centered content.

## Responsive Behavior

- **>768px**: Full sidebar (240px) with icon + text
- **<=768px**: Icon-only sidebar (60px), text hidden via CSS
- Sidebar always visible (no hamburger menu)

## Scope Exclusions

- No new JS frameworks or icon libraries
- No changes to API routes or backend logic
- No changes to Pico CSS source file
- Setup wizard keeps its centered layout (no sidebar), just gets dark theme
