# Sonarr-Style Dark Sidebar UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restyle the app to match Sonarr's visual language — dark grey background, light grey text, left sidebar navigation, purple link hovers, compact typography.

**Architecture:** CSS-only retheme on top of Pico CSS. Restructure `base.html` to use a sidebar layout via CSS Grid. Dark mode becomes the default (no toggle). Sidebar collapses to icon-only on mobile.

**Tech Stack:** Pico CSS (kept), CSS custom properties, Jinja2 templates, vanilla JS

---

### Task 1: Create Feature Branch

**Step 1: Create and switch to feature branch**

Run: `git checkout -b feature/dark-sidebar-ui`

**Step 2: Commit the design doc**

Run:
```bash
git add docs/plans/
git commit -m "docs: add dark sidebar UI design and implementation plan"
```

---

### Task 2: Rewrite sonarr-theme.css to Dark-First

**Files:**
- Modify: `src/splintarr/static/css/sonarr-theme.css`

This is the biggest single change. We're replacing the light-default color scheme with dark-first and adding sidebar layout CSS.

**Step 1: Replace sonarr-theme.css with dark-first theme**

Replace the entire content of `src/splintarr/static/css/sonarr-theme.css` with:

```css
/**
 * Sonarr-inspired dark theme for Splintarr
 *
 * Dark-first design with left sidebar navigation.
 * Built on top of Pico CSS with variable overrides.
 */

:root {
    /* Slate palette */
    --slate-950: #15171c;
    --slate-900: #1a1d23;
    --slate-800: #252832;
    --slate-700: #2c3034;
    --slate-600: #383d45;
    --slate-500: #5a6169;
    --slate-400: #7a8088;
    --slate-300: #9ca3af;
    --slate-200: #d1d5db;
    --slate-100: #f3f4f6;

    /* Brand colors */
    --brand-primary: #9333ea;
    --brand-primary-hover: #7e22ce;
    --brand-success: #48c774;
    --brand-warning: #ffb86c;
    --brand-danger: #ff5555;
    --brand-info: #a855f7;

    /* Override Pico CSS — dark defaults */
    --primary: var(--brand-primary);
    --primary-hover: var(--brand-primary-hover);
    --primary-focus: rgba(147, 51, 234, 0.25);
    --primary-inverse: #ffffff;

    /* Backgrounds */
    --background-color: var(--slate-900);
    --card-background-color: var(--slate-800);
    --card-border-color: var(--slate-600);
    --card-sectionning-background-color: var(--slate-700);

    /* Text — light on dark */
    --color: var(--slate-200);
    --h1-color: var(--slate-100);
    --h2-color: var(--slate-100);
    --h3-color: var(--slate-200);
    --h4-color: var(--slate-200);
    --h5-color: var(--slate-300);
    --h6-color: var(--slate-400);
    --muted-color: var(--slate-300);
    --muted-border-color: var(--slate-600);

    /* Forms — dark inputs */
    --form-element-background-color: var(--slate-700);
    --form-element-border-color: var(--slate-600);
    --form-element-color: var(--slate-200);
    --form-element-placeholder-color: var(--slate-400);
    --form-element-active-border-color: var(--brand-primary);
    --form-element-focus-color: var(--brand-primary);
    --form-element-disabled-background-color: var(--slate-800);
    --form-element-disabled-border-color: var(--slate-600);
    --form-element-disabled-opacity: 0.5;

    /* Buttons */
    --button-box-shadow: none;
    --button-hover-box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);

    /* Typography — compact */
    --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    --font-size: 14px;
    --line-height: 1.5;
    --font-weight: 400;
    --heading-weight: 600;

    /* Spacing & shape */
    --spacing: 1rem;
    --border-radius: 0.25rem;
    --outline-width: 2px;
    --transition: 150ms ease-in-out;

    /* Sidebar dimensions */
    --sidebar-width: 240px;
    --sidebar-collapsed-width: 60px;
    --sidebar-bg: var(--slate-950);
    --sidebar-border: var(--slate-700);

    /* Pico overrides for dark mode */
    --switch-background-color: var(--slate-600);
    --switch-checked-background-color: var(--brand-primary);
    --code-background-color: var(--slate-700);
    --code-color: var(--slate-200);
    --table-border-color: var(--slate-600);
    --table-row-stripped-background-color: rgba(0, 0, 0, 0.15);
    --dropdown-background-color: var(--slate-800);
    --dropdown-border-color: var(--slate-600);
    --dropdown-color: var(--slate-200);
    --dropdown-hover-background-color: var(--slate-700);
    --mark-background-color: rgba(147, 51, 234, 0.2);
    --mark-color: var(--slate-100);
    --del-color: var(--brand-danger);
    --ins-color: var(--brand-success);
}

/* ============================================
   Body & Typography
   ============================================ */

body {
    font-family: var(--font-family);
    font-size: var(--font-size);
    line-height: var(--line-height);
    color: var(--color);
    background-color: var(--background-color);
    margin: 0;
}

h1, h2, h3, h4, h5, h6 {
    font-weight: var(--heading-weight);
    line-height: 1.3;
    margin-bottom: 0.5rem;
}

h1 { font-size: 1.5rem; color: var(--h1-color); }
h2 { font-size: 1.25rem; color: var(--h2-color); }
h3 { font-size: 1.1rem; color: var(--h3-color); }
h4 { font-size: 1rem; color: var(--h4-color); }

p { color: var(--color); line-height: 1.5; }
ul li, ol li { color: var(--color); line-height: 1.5; }

hgroup { margin-bottom: 1.5rem; }
hgroup h1, hgroup h2, hgroup h3 { margin-bottom: 0.25rem; }
hgroup p {
    color: var(--muted-color);
    font-size: 0.9rem;
    font-weight: 400;
}

/* Links — light grey, purple on hover */
a { color: var(--slate-200); transition: color var(--transition); }
a:hover { color: var(--brand-primary); }

/* ============================================
   App Layout — Sidebar + Content
   ============================================ */

.app-layout {
    display: grid;
    grid-template-columns: var(--sidebar-width) 1fr;
    min-height: 100vh;
}

/* Sidebar */
.sidebar {
    background: var(--sidebar-bg);
    border-right: 1px solid var(--sidebar-border);
    display: flex;
    flex-direction: column;
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: var(--sidebar-width);
    z-index: 100;
    overflow-y: auto;
    overflow-x: hidden;
}

.sidebar-brand {
    padding: 1rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    border-bottom: 1px solid var(--sidebar-border);
    min-height: 3rem;
}

.sidebar-brand-icon {
    width: 28px;
    height: 28px;
    background: var(--brand-primary);
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: 700;
    font-size: 0.875rem;
    flex-shrink: 0;
}

.sidebar-brand-text {
    color: var(--slate-100);
    font-weight: 600;
    font-size: 1rem;
    white-space: nowrap;
    overflow: hidden;
}

/* Sidebar navigation */
.sidebar-nav {
    flex: 1;
    padding: 0.5rem 0;
}

.sidebar-nav ul {
    list-style: none;
    margin: 0;
    padding: 0;
}

.sidebar-nav li {
    margin: 0;
    padding: 0;
}

.sidebar-nav a {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.625rem 1rem;
    color: var(--slate-300);
    text-decoration: none;
    font-size: 0.875rem;
    font-weight: 500;
    border-left: 3px solid transparent;
    transition: all var(--transition);
    white-space: nowrap;
    overflow: hidden;
}

.sidebar-nav a:hover {
    color: var(--slate-100);
    background: rgba(255, 255, 255, 0.05);
}

.sidebar-nav a.active {
    color: var(--brand-primary);
    border-left-color: var(--brand-primary);
    background: rgba(147, 51, 234, 0.1);
}

.sidebar-nav .nav-icon {
    width: 20px;
    text-align: center;
    flex-shrink: 0;
    font-size: 1rem;
}

.sidebar-nav .nav-label {
    overflow: hidden;
    text-overflow: ellipsis;
}

.sidebar-nav .nav-badge {
    margin-left: auto;
    background: var(--brand-primary);
    color: white;
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.125rem 0.4rem;
    border-radius: 0.75rem;
    min-width: 1.25rem;
    text-align: center;
}

/* Sidebar sections */
.sidebar-section {
    padding-top: 0.5rem;
    margin-top: 0.5rem;
    border-top: 1px solid var(--sidebar-border);
}

/* Main content area */
.main-content {
    margin-left: var(--sidebar-width);
    padding: 1.5rem 2rem;
    min-height: 100vh;
    overflow-x: hidden;
}

.main-content > footer {
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--muted-border-color);
    text-align: center;
}

.main-content > footer small {
    color: var(--slate-400);
    font-size: 0.75rem;
}

.main-content > footer a {
    color: var(--slate-400);
}

.main-content > footer a:hover {
    color: var(--brand-primary);
}

/* ============================================
   Cards (article elements)
   ============================================ */

article {
    background: var(--card-background-color);
    border: 1px solid var(--card-border-color);
    border-radius: var(--border-radius);
    padding: 1.25rem;
    margin-bottom: 1rem;
    box-shadow: none;
}

article > header {
    background: transparent;
    color: var(--color);
    padding: 0 0 0.75rem 0;
    margin: 0 0 0.75rem 0;
    border-bottom: 1px solid var(--muted-border-color);
    border-radius: 0;
}

article > header h3,
article > header h4,
article > header h5 {
    margin-bottom: 0.125rem;
    color: var(--h3-color);
}

article > footer {
    background: transparent;
    color: var(--color);
    padding: 0.75rem 0 0 0;
    margin: 0.75rem 0 0 0;
    border-top: 1px solid var(--muted-border-color);
    border-radius: 0;
}

/* ============================================
   Buttons
   ============================================ */

button,
[type="submit"],
[type="button"],
[type="reset"],
[role="button"] {
    font-weight: 500;
    padding: 0.5rem 1rem;
    border-radius: var(--border-radius);
    transition: all var(--transition);
    box-shadow: var(--button-box-shadow);
    height: auto;
    line-height: 1.5;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    white-space: nowrap;
    vertical-align: middle;
    text-decoration: none;
    font-size: 0.875rem;
}

button:hover,
[type="submit"]:hover,
[type="button"]:hover,
[role="button"]:hover {
    box-shadow: var(--button-hover-box-shadow);
}

button:not([role="button"]),
[type="submit"] {
    font-weight: 600;
}

/* ============================================
   Forms
   ============================================ */

input,
select,
textarea {
    border-radius: var(--border-radius);
    border: 1px solid var(--form-element-border-color);
    transition: all var(--transition);
    font-size: 0.875rem;
    background-color: var(--form-element-background-color);
    color: var(--form-element-color);
}

input:focus,
select:focus,
textarea:focus {
    border-color: var(--form-element-active-border-color);
    box-shadow: 0 0 0 3px var(--primary-focus);
}

label {
    font-weight: 500;
    margin-bottom: 0.375rem;
    color: var(--color);
    font-size: 0.875rem;
}

label small {
    display: block;
    margin-top: 0.125rem;
    font-weight: 400;
    color: var(--muted-color);
    font-size: 0.8125rem;
}

/* ============================================
   Status Badges
   ============================================ */

.badge {
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.5rem;
    border-radius: 0.2rem;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.025em;
}

.badge-success { background: rgba(72, 199, 116, 0.15); color: var(--brand-success); }
.badge-warning { background: rgba(255, 184, 108, 0.15); color: var(--brand-warning); }
.badge-danger { background: rgba(255, 85, 85, 0.15); color: var(--brand-danger); }
.badge-info { background: rgba(168, 85, 247, 0.15); color: var(--brand-info); }

/* ============================================
   Alerts
   ============================================ */

.alert {
    padding: 0.75rem 1rem;
    border-radius: var(--border-radius);
    margin-bottom: 1rem;
    border-left: 3px solid;
    font-size: 0.875rem;
}

.alert-info { background: rgba(168, 85, 247, 0.1); border-color: var(--brand-info); color: var(--brand-info); }
.alert-success { background: rgba(72, 199, 116, 0.1); border-color: var(--brand-success); color: var(--brand-success); }
.alert-warning { background: rgba(255, 184, 108, 0.1); border-color: var(--brand-warning); color: var(--brand-warning); }
.alert-danger { background: rgba(255, 85, 85, 0.1); border-color: var(--brand-danger); color: var(--brand-danger); }

/* ============================================
   Setup Wizard (no sidebar, centered)
   ============================================ */

.setup-wizard-container {
    max-width: 600px;
    margin: 2rem auto;
    padding: 0 1rem;
}

.setup-progress {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    margin: 1.5rem 0;
    padding: 0;
    list-style: none;
}

.setup-progress .step {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.5rem 0.75rem;
    background: var(--slate-800);
    border: 1px solid var(--slate-600);
    border-radius: var(--border-radius);
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--slate-400);
    transition: all var(--transition);
    min-height: 2.5rem;
}

.setup-progress .step.completed {
    background: var(--slate-700);
    color: var(--slate-200);
    border-color: var(--slate-500);
}

.setup-progress .step.active {
    background: var(--brand-primary);
    color: white;
    border-color: var(--brand-primary);
    font-weight: 600;
}

.setup-progress .step::before {
    content: attr(data-step);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 50%;
    background: var(--slate-600);
    color: var(--slate-300);
    font-weight: 600;
    font-size: 0.75rem;
    margin-right: 0.375rem;
    flex-shrink: 0;
}

.setup-progress .step.active::before {
    background: white;
    color: var(--brand-primary);
}

.setup-progress .step.completed::before {
    background: var(--brand-success);
    color: white;
    content: "\2713";
    font-size: 0.875rem;
}

.setup-content { margin-top: 1.5rem; }
.setup-content article { padding: 1.5rem; }
.setup-content h3 { color: var(--h3-color); margin-top: 1rem; margin-bottom: 0.75rem; font-size: 1.1rem; }
.setup-content h3:first-child { margin-top: 0; }
.setup-content ul, .setup-content ol { margin-left: 1.25rem; margin-bottom: 0.75rem; }
.setup-content li { margin-bottom: 0.375rem; }

.form-group { margin-bottom: 1.25rem; }
.form-group:last-child { margin-bottom: 0; }

.setup-actions {
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    margin-top: 1.5rem;
    gap: 0.5rem;
}

.setup-actions > *:first-child { margin-right: auto; }
.setup-actions .btn-group { display: flex; gap: 0.5rem; }

/* ============================================
   Login Page (centered, no sidebar)
   ============================================ */

.login-container {
    max-width: 400px;
    margin: 0 auto;
    padding: 0 1rem;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.login-container article {
    padding: 2rem;
}

.login-container h1 {
    text-align: center;
    margin-bottom: 0.5rem;
}

.login-container p {
    text-align: center;
    color: var(--muted-color);
    margin-bottom: 1.5rem;
}

/* ============================================
   Responsive — sidebar collapse to icon-only
   ============================================ */

@media (max-width: 768px) {
    .app-layout {
        grid-template-columns: var(--sidebar-collapsed-width) 1fr;
    }

    .sidebar {
        width: var(--sidebar-collapsed-width);
    }

    .sidebar-brand-text,
    .sidebar-nav .nav-label,
    .sidebar-nav .nav-badge {
        display: none;
    }

    .sidebar-brand {
        justify-content: center;
        padding: 0.75rem;
    }

    .sidebar-nav a {
        justify-content: center;
        padding: 0.75rem;
        border-left-width: 2px;
    }

    .main-content {
        margin-left: var(--sidebar-collapsed-width);
        padding: 1rem;
    }

    .setup-wizard-container { margin: 1rem auto; }
    .setup-progress { flex-direction: column; gap: 0.25rem; }

    h1 { font-size: 1.25rem; }
    h2 { font-size: 1.1rem; }

    article { padding: 1rem; }
}

@media (max-width: 576px) {
    .setup-wizard-container { padding: 0 0.5rem; }
    hgroup p { font-size: 0.8125rem; }
}

/* ============================================
   Misc
   ============================================ */

[aria-busy="true"]::after {
    border-color: var(--brand-primary);
    border-right-color: transparent;
}

:focus-visible {
    outline: var(--outline-width) solid var(--primary);
    outline-offset: 2px;
}

html { scroll-behavior: smooth; }
```

**Step 2: Verify file saved correctly**

Run: `wc -l src/splintarr/static/css/sonarr-theme.css`
Expected: ~430 lines

**Step 3: Commit**

```bash
git add src/splintarr/static/css/sonarr-theme.css
git commit -m "style: rewrite sonarr-theme.css to dark-first with sidebar layout"
```

---

### Task 3: Update custom.css for Dark Theme

**Files:**
- Modify: `src/splintarr/static/css/custom.css`

**Step 1: Replace custom.css with dark-compatible styles**

Replace the entire content of `src/splintarr/static/css/custom.css` with:

```css
/**
 * Custom styles for Splintarr Dashboard
 * Dark theme compatible — extends sonarr-theme.css
 */

:root {
    --font-family-monospace: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
}

/* Status indicators */
.status-healthy { color: var(--brand-success); }
.status-unhealthy { color: var(--brand-danger); }
.status-warning { color: var(--brand-warning); }
.status-unknown { color: var(--muted-color); }

/* Grid */
.grid { grid-gap: 1rem; }
.grid > article { margin-bottom: 0; }

/* Definition lists in cards */
article dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.375rem 0.75rem;
    margin-bottom: 0.75rem;
}

article dl dt {
    font-weight: 600;
    color: var(--muted-color);
    font-size: 0.8125rem;
}

article dl dd { margin: 0; font-size: 0.875rem; }

/* Progress bars */
progress { height: 0.375rem; }

/* Code */
code {
    font-family: var(--font-family-monospace);
    font-size: 0.8125em;
    padding: 0.125rem 0.375rem;
    background-color: var(--code-background-color);
    border-radius: var(--border-radius);
    color: var(--code-color);
}

/* Tables */
table { font-size: 0.8125rem; }

table th {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.6875rem;
    letter-spacing: 0.5px;
    color: var(--muted-color);
}

table td { color: var(--color); }
table code { font-size: 0.75em; }

/* Modal dialogs */
dialog { background: transparent; }
dialog::backdrop { background: rgba(0, 0, 0, 0.6); }
dialog article { margin: 0; max-width: 500px; }
dialog article header { margin-bottom: 0.75rem; }
dialog article footer { margin-top: 0.75rem; }

/* Button groups in footers */
footer button,
footer a[role="button"] { margin-bottom: 0; }

/* Statistics cards */
article hgroup h2 {
    font-size: 2rem;
    font-weight: 700;
    margin-bottom: 0.125rem;
    color: var(--primary);
}

article hgroup p {
    margin-top: 0;
    margin-bottom: 0.25rem;
    text-transform: uppercase;
    font-size: 0.6875rem;
    letter-spacing: 1px;
    color: var(--muted-color);
}

/* Empty states */
.empty-state {
    text-align: center;
    color: var(--muted-color);
    padding: 2rem 1rem;
}

.empty-state p { margin-bottom: 0.75rem; }

/* Utility classes */
.text-center { text-align: center; }
.text-right { text-align: right; }
.text-muted { color: var(--muted-color); }
.text-success { color: var(--brand-success); }
.text-error { color: var(--brand-danger); }
.text-warning { color: var(--brand-warning); }

/* Flash messages container */
.flash-container {
    padding: 0 2rem;
}

/* Responsive */
@media (max-width: 768px) {
    .grid { grid-template-columns: 1fr; }
    article dl { grid-template-columns: 1fr; gap: 0.125rem; }
    table { font-size: 0.75rem; }
    .flash-container { padding: 0 1rem; }
}

/* Loading states */
[aria-busy="true"] { pointer-events: none; }

/* Pagination */
nav[aria-label="Pagination"] ul {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 0.5rem;
    list-style: none;
    padding: 0;
    margin: 1rem 0;
}

nav[aria-label="Pagination"] li { margin: 0; }

nav[aria-label="Pagination"] a[role="button"] {
    margin: 0;
    padding: 0.375rem 0.75rem;
    font-size: 0.8125rem;
}
```

**Step 2: Commit**

```bash
git add src/splintarr/static/css/custom.css
git commit -m "style: update custom.css for dark theme compatibility"
```

---

### Task 4: Restructure base.html with Sidebar Layout

**Files:**
- Modify: `src/splintarr/templates/base.html`

This is the structural change — replacing the horizontal nav with a sidebar layout.

**Step 1: Replace base.html**

Replace the entire content of `src/splintarr/templates/base.html` with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Splintarr{% endblock %}</title>

    <!-- Pico CSS -->
    <link rel="stylesheet" href="/static/css/pico.min.css">
    <link rel="stylesheet" href="/static/css/sonarr-theme.css">
    <link rel="stylesheet" href="/static/css/custom.css">

    {% block extra_head %}{% endblock %}
</head>
<body>
    {% if user %}
    <!-- Authenticated layout: sidebar + content -->
    <div class="app-layout">
        <aside class="sidebar">
            <div class="sidebar-brand">
                <div class="sidebar-brand-icon">S</div>
                <span class="sidebar-brand-text">Splintarr</span>
            </div>
            <nav class="sidebar-nav">
                <ul>
                    <li>
                        <a href="/dashboard" class="{{ 'active' if active_page == 'dashboard' else '' }}">
                            <span class="nav-icon">&#9673;</span>
                            <span class="nav-label">Dashboard</span>
                        </a>
                    </li>
                    <li>
                        <a href="/dashboard/instances" class="{{ 'active' if active_page == 'instances' else '' }}">
                            <span class="nav-icon">&#9678;</span>
                            <span class="nav-label">Instances</span>
                        </a>
                    </li>
                    <li>
                        <a href="/dashboard/search-queues" class="{{ 'active' if active_page == 'queues' else '' }}">
                            <span class="nav-icon">&#9776;</span>
                            <span class="nav-label">Queues</span>
                        </a>
                    </li>
                    <li>
                        <a href="/dashboard/search-history" class="{{ 'active' if active_page == 'history' else '' }}">
                            <span class="nav-icon">&#9719;</span>
                            <span class="nav-label">History</span>
                        </a>
                    </li>
                </ul>
                <div class="sidebar-section">
                    <ul>
                        <li>
                            <a href="/dashboard/settings" class="{{ 'active' if active_page == 'settings' else '' }}">
                                <span class="nav-icon">&#9881;</span>
                                <span class="nav-label">Settings</span>
                            </a>
                        </li>
                        <li>
                            <a href="#" data-action="logout">
                                <span class="nav-icon">&#9211;</span>
                                <span class="nav-label">Logout</span>
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>
        </aside>

        <div class="main-content">
            <!-- Flash messages -->
            {% include "components/flash.html" %}

            <!-- Page content -->
            {% block content %}{% endblock %}

            <!-- Footer -->
            <footer>
                <small>
                    Splintarr v0.1.0 &middot;
                    <a href="https://github.com/menottim/splintarr" target="_blank">GitHub</a>
                </small>
            </footer>
        </div>
    </div>
    {% else %}
    <!-- Unauthenticated layout: no sidebar -->
    {% include "components/flash.html" %}
    {% block unauthenticated_content %}{% endblock %}
    {% endif %}

    <!-- Scripts -->
    <script nonce="{{ request.state.csp_nonce }}">
        document.querySelectorAll('[data-action="logout"]').forEach(function(el) {
            el.addEventListener('click', function(e) { e.preventDefault(); logout(); });
        });

        function logout() {
            fetch('/api/auth/logout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            }).then(() => { window.location.href = '/login'; });
        }
    </script>

    {% block extra_scripts %}{% endblock %}
</body>
</html>
```

**Key changes:**
- Authenticated pages get `<div class="app-layout">` with sidebar + main-content
- Unauthenticated pages use `{% block unauthenticated_content %}` (no sidebar)
- Active page highlighting via `active_page` template variable
- Footer moved inside `.main-content`
- Flash messages positioned inside `.main-content` for sidebar pages

**Step 2: Commit**

```bash
git add src/splintarr/templates/base.html
git commit -m "feat: restructure base.html with sidebar navigation layout"
```

---

### Task 5: Update Login Template for Dark Centered Layout

**Files:**
- Modify: `src/splintarr/templates/auth/login.html`

The login page needs to use the `unauthenticated_content` block instead of `content`.

**Step 1: Update login.html**

Replace the entire content of `src/splintarr/templates/auth/login.html` with:

```html
{% extends "base.html" %}

{% block title %}Login - Splintarr{% endblock %}

{% block unauthenticated_content %}
<div class="login-container">
    <article>
        <h1>Splintarr</h1>
        <p>Sign in to your account</p>

        <form id="loginForm">
            <label for="username">Username</label>
            <input type="text" id="username" name="username" required autocomplete="username" autofocus>

            <label for="password">Password</label>
            <input type="password" id="password" name="password" required autocomplete="current-password">

            <button type="submit">Sign In</button>
        </form>
    </article>
</div>
{% endblock %}

{% block extra_scripts %}
<script nonce="{{ request.state.csp_nonce }}">
    document.getElementById('loginForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        const btn = this.querySelector('button[type="submit"]');
        btn.setAttribute('aria-busy', 'true');
        btn.textContent = 'Signing in...';

        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value
                })
            });

            if (response.ok) {
                window.location.href = '/dashboard';
            } else {
                const data = await response.json();
                alert(data.detail || 'Login failed');
            }
        } catch (error) {
            alert('Connection error. Please try again.');
        } finally {
            btn.removeAttribute('aria-busy');
            btn.textContent = 'Sign In';
        }
    });
</script>
{% endblock %}
```

**Step 2: Commit**

```bash
git add src/splintarr/templates/auth/login.html
git commit -m "style: update login page for dark centered layout"
```

---

### Task 6: Update Setup Templates for Dark Theme

**Files:**
- Modify: `src/splintarr/templates/setup/welcome.html`
- Modify: `src/splintarr/templates/setup/admin.html`
- Modify: `src/splintarr/templates/setup/instance.html`
- Modify: `src/splintarr/templates/setup/complete.html`

Setup templates need to use `unauthenticated_content` block instead of `content`, since the user isn't logged in during setup and there's no sidebar.

**Step 1: Update welcome.html — change block name**

In `src/splintarr/templates/setup/welcome.html`, change:
- `{% block content %}` to `{% block unauthenticated_content %}`
- `{% endblock %}` (the matching one) stays as is

**Step 2: Update admin.html — change block name**

In `src/splintarr/templates/setup/admin.html`, change:
- `{% block content %}` to `{% block unauthenticated_content %}`

**Step 3: Update instance.html — change block name**

In `src/splintarr/templates/setup/instance.html`, change:
- `{% block content %}` to `{% block unauthenticated_content %}`

**Step 4: Update complete.html — change block name**

In `src/splintarr/templates/setup/complete.html`, change:
- `{% block content %}` to `{% block unauthenticated_content %}`

**Step 5: Commit**

```bash
git add src/splintarr/templates/setup/
git commit -m "style: update setup wizard templates for unauthenticated dark layout"
```

---

### Task 7: Add active_page to Dashboard Route Handlers

**Files:**
- Modify: `src/splintarr/api/dashboard.py`

The sidebar needs an `active_page` template variable to highlight the current page. Each route handler's `TemplateResponse` context needs this added.

**Step 1: Read the current dashboard.py to find all TemplateResponse calls**

Read `src/splintarr/api/dashboard.py` and find every `templates.TemplateResponse(...)` call.

**Step 2: Add active_page to each route's context**

For each route handler, add `"active_page": "<page>"` to the template context dict:

| Route | Template | active_page value |
|-------|----------|-------------------|
| `/dashboard` | `dashboard/index.html` | `"dashboard"` |
| `/dashboard/instances` | `dashboard/instances.html` | `"instances"` |
| `/dashboard/search-queues` | `dashboard/search_queues.html` | `"queues"` |
| `/dashboard/search-history` | `dashboard/search_history.html` | `"history"` |
| `/dashboard/settings` | `dashboard/settings.html` | `"settings"` |

Each `TemplateResponse` context dict should have `"active_page": "..."` added.

**Step 3: Commit**

```bash
git add src/splintarr/api/dashboard.py
git commit -m "feat: add active_page to template context for sidebar highlighting"
```

---

### Task 8: Visual Verification

**Step 1: Build and run Docker**

```bash
docker compose build && docker compose up -d
```

**Step 2: Check health**

Run: `curl http://localhost:7337/health`
Expected: `{"status":"ok"}`

**Step 3: Verify login page**

Open `http://localhost:7337/login` in browser.
Expected: Dark background, centered login card, light grey text, purple button.

**Step 4: Verify dashboard**

Login and check dashboard.
Expected: Left sidebar with icon + text nav items, dark content area, purple active indicator on Dashboard link, compact typography.

**Step 5: Verify mobile sidebar**

Resize browser to < 768px width.
Expected: Sidebar collapses to icon-only (60px), content fills rest of screen.

**Step 6: Check setup wizard**

Navigate to `/setup` (or reset setup state).
Expected: Dark background, centered wizard, no sidebar, progress steps visible.

---

### Task 9: Run Linter

**Step 1: Run ruff on any modified Python files**

```bash
/Users/mminutillo/Library/Python/3.14/bin/poetry run ruff check src/splintarr/api/dashboard.py
```

Expected: No new errors.

**Step 2: Fix any lint issues if found**

**Step 3: Final commit if any fixes were needed**

---

### Task 10: Final Commit and Summary

**Step 1: Check git status**

Run: `git status`

Verify all changes are committed.

**Step 2: Review commit log**

Run: `git log --oneline feature/dark-sidebar-ui --not main`

Should show ~6-7 commits covering:
1. Design doc
2. sonarr-theme.css rewrite
3. custom.css update
4. base.html restructure
5. Login template update
6. Setup template updates
7. Dashboard route active_page additions
