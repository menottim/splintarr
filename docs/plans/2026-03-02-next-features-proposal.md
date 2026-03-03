# Splintarr Next Features Proposal

> **Date:** 2026-03-02 (decisions finalized 2026-03-03)
> **Context:** Exploratory research for post-v1.0.2-alpha feature set (Sonarr-only, balanced mix)
> **Status:** Approved — ready for implementation

---

## Research Summary

### External Research Sources

- [Sonarr Wanted wiki](https://wiki.servarr.com/sonarr/wanted) — Missing/Cutoff Unmet pages, "Search All" behavior
- [Sonarr GitHub #6309](https://github.com/Sonarr/Sonarr/issues/6309) — Long Term Search Missing (rejected by Sonarr team, told to use external tools)
- [Sonarr GitHub #3067](https://github.com/Sonarr/Sonarr/issues/3067) — LastSearchTime prioritization (search never-searched first)
- [Sonarr GitHub #3657](https://github.com/Sonarr/Sonarr/issues/3657) — Custom filters for Wanted (users want year, quality profile, series filtering)
- [Sonarr GitHub #6435](https://github.com/Sonarr/Sonarr/issues/6435) — Skip episode-by-episode search (season packs preferred for anime)
- [Sonarr GitHub #6742](https://github.com/Sonarr/Sonarr/issues/6742) — Cutoff Unmet monitoring option
- [Sonarr GitHub #5304](https://github.com/Sonarr/Sonarr/issues/5304) — Custom Formats not included in Cutoff Unmet
- [TRaSH Guides — Quality Profiles](https://trash-guides.info/Sonarr/sonarr-setup-quality-profiles/) — CF scoring, upgrade paths
- [TRaSH Guides — Limited API Indexers](https://trash-guides.info/Prowlarr/prowlarr-setup-limited-api/) — Prowlarr sync profiles for limited indexers
- [Scoutarr](https://github.com/SuFxGIT/scoutarr) — Primary competitor (TypeScript, multi-arr, tag-based workflow)
- [Recyclarr](https://recyclarr.dev/wiki/features/) — CF/quality profile automation (config-as-code)

### Key Findings

1. **Sonarr explicitly refuses to add backlog searching** ([#6309](https://github.com/Sonarr/Sonarr/issues/6309)). The maintainers say "use external tools." This validates Splintarr's entire reason to exist.

2. **The #1 community pain point** is hitting indexer API limits when searching large backlogs. Users with 5,000+ missing episodes can't use "Search All" without getting banned. Splintarr already solves this — but awareness of the specific failure modes informs new features.

3. **Scoutarr** (Upgradinatorr successor) is the closest competitor. Key differences:
   - Scoutarr uses a **tag-based workflow** (tag searched items to skip them next time). Splintarr uses **DB-tracked per-episode history** — more sophisticated but invisible to the user.
   - Scoutarr supports **4 \*arr apps** (Radarr, Sonarr, Lidarr, Readarr). Splintarr is Sonarr-only (for now).
   - Scoutarr has **CF score history tracking**. Splintarr does not surface CF data at all.
   - Splintarr has **significantly deeper search intelligence** (adaptive scoring, tiered cooldowns, grab feedback, season packs). Scoutarr is simpler.

4. **Custom Format awareness is a major gap**. Sonarr v4 heavily relies on Custom Formats for upgrade decisions, but Splintarr currently treats "cutoff unmet" as a binary — it doesn't know *why* something is cutoff unmet (quality vs CF score) or *how far* from the target it is.

5. **Users want filtered/targeted searching** ([#3657](https://github.com/Sonarr/Sonarr/issues/3657)). "Search all cutoff unmet from 2010 and higher." "Search only items in a specific quality profile." The Custom Strategy framework exists in Splintarr but is stubbed.

### API Spike: Quality Data Availability (Confirmed)

Sonarr's `/api/v3/episodefile` endpoint returns:
- `quality.quality.name` (e.g., "WEBDL-1080p")
- `quality.quality.resolution` (e.g., 1080)
- `quality.quality.source` (e.g., "web")
- `customFormats` array (custom format objects)
- `customFormatScore` integer (total CF score)

`/api/v3/qualityprofile` returns cutoff target and upgrade-until CF score. **Quality-gap scoring (F5) is fully feasible.**

---

## Approved Features

### v1.1.0 — Visibility (ship PR-per-feature, merge as ready)

**Theme:** Make everything visible. Users should see what's happening, what will happen, and what has happened — all in real time.

#### F2. WebSocket Real-Time Activity Feed

**Problem:** Dashboard polling at 15-30 second intervals feels sluggish.

**Approved scope:**
- WebSocket endpoint at `/ws/activity`
- **Replaces ALL polling** — stats, system status, activity, indexer health. One connection, all data.
- In-process event bus (no Redis — single-worker)
- Events: `search_started`, `search_item_result`, `search_completed`, `search_failed`, `instance_health_changed`, `library_sync_progress`, `stats_updated`, `indexer_health_updated`
- Auth: Validate JWT cookie on WS upgrade handshake
- Reconnect: Auto-reconnect with exponential backoff
- Graceful fallback to polling if WS fails

**Effort:** Medium

---

#### F3. Search Progress & Live Queue View

**Problem:** No visibility into what's happening during queue execution.

**Approved scope:**
- **Queue detail page:** Full live progress view — progress bar, current item, items completed/remaining, elapsed/estimated time, per-item results streaming in (found/not found/skipped with reasons)
- **Dashboard:** Compact "currently running" indicator with progress bar
- Powered by F2 WebSocket events
- Persisted as enriched `search_metadata` on SearchHistory

**Effort:** Low-Medium

---

#### F6. Search Dry Run / Preview Mode

**Problem:** No way to see what a queue would search without running it.

**Approved scope:**
- **Queue creation modal:** "Preview" button runs scoring/filtering pipeline without executing searches
- **Existing queue detail page:** "Preview next run" button shows what would happen if it ran now
- Returns: item list in priority order with scores, reasons, estimated API cost, season pack groupings, cooldown skips
- Reuses existing pipeline — just skips the final search command

**Effort:** Low

---

#### F10. Search History Analytics (Mini)

**Problem:** No trend visibility on search effectiveness.

**Approved scope:**
- Single dashboard card: "Last 7 Days"
- Searches run, items found, grabs confirmed (with trend arrows vs previous 7 days)
- Top 3 most-searched series
- Indexer hit/miss rates
- Inline SVG sparklines (no JS chart library)
- Data from existing SearchHistory + LibraryItem tables

**Effort:** Low

---

#### F11. Bulk Queue Operations

**Problem:** Managing multiple queues requires clicking into each individually.

**Approved scope:**
- Checkboxes on Queues page for multi-select
- Bulk actions: Pause selected, Resume selected, Delete selected
- Header buttons: "Pause All" / "Resume All" / "Run All Now" (with confirmation)

**Effort:** Low

---

### v1.2.0 — Smart Searching

**Theme:** Search smarter, not harder. Target specific content, respect API budgets, prioritize by quality gap.

#### F1. Custom Strategy Filters

**Problem:** Custom Strategy is stubbed. Users can't target searches.

**Approved scope — simple dropdowns:**
- Include checkboxes: Missing, Cutoff Unmet (can combine — explicit opt-in exception to strategy isolation)
- Year range: from/to dropdowns
- Quality profile: dropdown (populated from Sonarr)
- Series status: dropdown (continuing, ended, upcoming, any)
- No tag filtering in v1.2 (can add later)
- Filters applied client-side after Sonarr API fetch
- Integrates with F6 dry run for previewing filter results

**Effort:** Medium

---

#### F4. Indexer Budget Visibility & Forecasting

**Problem:** Users don't know API budget status or how queue config affects it.

**Approved scope:**
- Dashboard: Per-indexer API usage as progress bars (used/limit)
- Queue creation: Estimated API cost preview ("~15 calls per run, 85 remaining today")
- Budget alerts: Discord/Apprise notification at 20% remaining (configurable)
- **Smart batch auto-sizing: ON by default.** If budget is low, automatically reduce `max_items_per_run` for that execution. User can disable per-queue.

**Effort:** Medium

---

#### F5. Quality-Aware Search Intelligence

**Problem:** Cutoff unmet is binary. No quality gap awareness.

**API spike confirmed:** Sonarr returns `quality.quality.resolution`, `quality.quality.source`, `customFormats`, and `customFormatScore` on episode files. Quality profiles expose cutoff and upgrade-until targets.

**Approved scope — full implementation:**
- Fetch current quality + CF score per episode file during sync
- Fetch quality profile cutoff and upgrade-until CF score targets
- New **quality gap scoring factor** in the scoring engine:
  - Resolution gap (720p→1080p = large gap, WEB-DL 1080p→Bluray 1080p = small gap)
  - CF score gap (current score vs upgrade-until target)
  - Larger gap = higher priority
- Library detail page: "Currently: HDTV-720p (score 5) → Target: Bluray-1080p (score 15)"
- Search logs: "large quality gap (720p → 1080p Bluray)"

**Effort:** Medium

---

#### F8. Queue Scheduling Improvements

**Problem:** Fixed-interval only. No time-of-day or day-of-week control.

**Approved scope — three schedule modes:**
- **Interval** (existing): "Every N hours"
- **Daily:** "Run at [HH:MM] every day" with time picker
- **Weekly:** "Run at [HH:MM] on [Mon/Wed/Fri]" with day checkboxes + time picker
- **Jitter:** Random 0-15 minute offset (prevents thundering herd)
- Uses APScheduler CronTrigger (already a dependency)

**Effort:** Low-Medium

---

### v1.3.0 — Polish & Reach

**Theme:** Broaden appeal. More notification services, better onboarding, richer library views.

#### F7. Apprise Notification Integration

**Problem:** Discord-only limits adoption.

**Approved scope:**
- Full [Apprise](https://github.com/caronc/apprise) integration (90+ notification services)
- User enters Apprise URL strings in Settings
- Keep existing Discord as primary (backward compat)
- Apprise handles formatting and delivery for all additional services

**Effort:** Low

---

#### F9. Series Completion Cards

**Problem:** No per-series progress visibility.

**Approved scope:**
- Library page section: "Completion Progress" sorted by % complete
- Compact cards: small poster, completion bar, missing/total count
- Filters: most incomplete first, most recently aired, closest to complete

**Effort:** Low

---

#### F12. Queue Recommendations

**Problem:** New users don't know how to configure queues.

**Approved scope:**
- Post-sync library analysis with data-driven queue recommendations
- "You have 342 missing episodes. We recommend batch size 20, every 6 hours. Backlog covered in ~4 days."
- Indexer budget awareness: sizes batches to fit within Prowlarr limits
- One-click "Create recommended queues" button
- Shown on Getting Started guide and empty Queues page

**Effort:** Medium

---

#### Config Import (deferred from alpha)

- Companion to existing Config Export
- Upload JSON to restore instances, queues, exclusions, notifications
- Conflict resolution for duplicate names, re-entry of API keys

**Effort:** Medium

---

## Competitive Positioning (Post-Implementation)

| Capability | Splintarr (proposed) | Scoutarr | Native Sonarr |
|---|---|---|---|
| Automated backlog search | Yes | Yes | No |
| Adaptive scoring/prioritization | Yes + quality-aware | No | No |
| Per-episode tracking | DB-tracked | Tag-based (coarser) | No |
| Season pack intelligence | Yes | No | Manual only |
| Indexer budget forecasting + auto-sizing | Yes | No | No |
| Custom search filters | Year, profile, status | Tag filtering only | No |
| Real-time activity | WebSocket push | Live dashboard | No |
| Search preview/dry run | Yes | No | No |
| Notification services | 90+ via Apprise | Discord/Notifiarr/Pushover | 10+ native |
| Quality gap scoring | Resolution + CF score | CF score history | No |
| Cron scheduling + jitter | Yes | Basic scheduler | No |
| Queue recommendations | Yes | No | No |

---

## Resolved Questions

| # | Question | Decision |
|---|----------|----------|
| 1 | F1 filter complexity | Simple dropdowns: year, quality profile, series status. No tags in v1.2. |
| 2 | F2 WebSocket scope | Replace ALL polling — one WS connection for everything. |
| 3 | F5 quality data availability | **Confirmed via API spike.** Sonarr exposes resolution, source, CF score, CF list on episodefile endpoint. Full implementation approved. |
| 4 | F7 Apprise vs native | Apprise — maximum reach, one dependency. |
| 5 | Release cadence | PR per feature, merge to main as ready. Tag release when all features for a version are merged. |
| 6 | F4 auto-shrink behavior | Auto by default. User can disable per-queue. |
| 7 | F3 progress location | Full view on queue detail page + compact indicator on dashboard. |
| 8 | F6 dry run availability | Both queue creation modal AND "Preview next run" on existing queues. |
| 9 | F8 scheduling UI | Three modes: interval (existing), daily (time picker), weekly (day checkboxes + time). Jitter included. |
| 10 | F10 analytics scope | Single dashboard card, 7-day trends. Keep it simple. |
| 11 | F11 timing | Stays in v1.1 — quick to build, rounds out the release. |
