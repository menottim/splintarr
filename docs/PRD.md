# Splintarr — Product Requirements Document

> **Living document.** Updated as features are implemented, priorities shift, or new requirements emerge. This is the sole source of truth; versioned PRDs have been retired.

**Last updated:** 2026-03-01

---

## Vision

Splintarr is the intelligent search scheduler that Sonarr and Radarr should have built in. It fills the gap between RSS-based new release monitoring (what Sonarr/Radarr do well) and backlog management (what they don't do at all). It provides scheduled, throttled, indexer-aware searching with adaptive prioritization — a "set and forget" solution for homelab operators.

## Target User

Solo homelab operator managing 1-5 Sonarr/Radarr instances behind Prowlarr, with libraries of 100-5,000 items. Values simplicity over configurability. Multi-user is out of scope.

## Design Principles

1. **Strategy isolation** — Missing and Cutoff Unmet are fundamentally different intents and must never be combined or auto-selected. "Missing" includes intentionally deleted content; "Cutoff Unmet" only upgrades existing files. Every feature must respect this boundary.
2. **Indexer respect** — Never overwhelm indexers. Throttle intelligently, adapt to limits, and spend API calls where they're most likely to succeed.
3. **Transparency** — Every search decision (why an item was searched, skipped, or deprioritized) should be visible in logs and the UI.
4. **Homelab-first** — Docker-first, single-container, no external dependencies beyond Sonarr/Radarr/Prowlarr. No cloud, no Redis, no complexity.
5. **Stay focused** — Search automation only. Don't try to replace the *arr apps. The community rejected Huntarr's scope creep and Splintarr should learn from that.

---

## Why Splintarr Exists

Sonarr and Radarr rely on RSS feeds for ongoing content — polling indexers every 15-60 minutes for newly posted releases. This handles future content but does nothing for backlogs. The built-in "Search All Missing" button sends all requests at once, overwhelming indexers. There is no scheduled, throttled backlog search, and the developers have indicated this is by design.

| Community Pain Point | Evidence |
|----------------------|----------|
| No scheduled backlog search | [Sonarr Forum: Scheduled Missing Search](https://forums.sonarr.tv/t/scheduled-missing-search/12641), [Trickle Mode](https://forums.sonarr.tv/t/missing-episodes-backlog-scan-trickle-mode/3933) |
| "Search All" overwhelms indexers | [Sonarr #1359](https://github.com/Sonarr/Sonarr/issues/1359), [#4907](https://github.com/Sonarr/Sonarr/issues/4907) |
| No season pack search option | [Sonarr #4229](https://github.com/Sonarr/Sonarr/issues/4229) |
| No search-by-age prioritization | [Sonarr #3067](https://github.com/Sonarr/Sonarr/issues/3067) |
| Re-downloads of deleted content | Users who delete episodes see them re-downloaded by "missing" searches |

### Competing Tools & Landscape

| Tool | Status | Approach | Splintarr Advantage |
|------|--------|----------|---------------------|
| Huntarr | **Abandoned** (Feb 2025) | Batch-based, hourly API caps, multi-arr support | See below |
| [NewtArr](https://github.com/elfhosted/newtarr) | Maintenance-only fork of Huntarr v6.6.3 | Same as Huntarr pre-controversy | Active development, security-first design, search intelligence |
| [missarr](https://github.com/l3uddz/missarr) | Active | CLI, config-file | Full web UI, scheduling, analytics, no scripting required |
| [n8n workflow](https://n8n.io/workflows/5927) | Active | Automation platform | Self-contained Docker app, no n8n infrastructure needed |

#### The Huntarr Incident (February 2025)

Huntarr was the most popular tool in this space until critical security vulnerabilities were publicly disclosed ([PiunikaWeb](https://piunikaweb.com/2026/02/24/huntarr-security-vulnerability-arr-api-keys-exposed/), [Lawrence Systems](https://forums.lawrencesystems.com/t/what-the-huntarr-controversy-teaches-about-self-hosted-security-youtube-release/26539)):

- **Unauthenticated API key exposure**: Anyone on the network (or internet, if exposed) could pull Sonarr/Radarr/Prowlarr API keys without logging in
- **Unauthenticated 2FA enrollment**: Allowed full account takeover with no password
- **Unauthenticated setup clear**: Attacker could reset the app and create a new owner account
- The project was 100% AI/vibe-coded with no code review or PR process
- When vulnerabilities were reported, the developer deleted the GitHub repo, Discord server, and went dark
- TrueNAS removed Huntarr from their app catalog ([Issue #4458](https://github.com/truenas/apps/issues/4458))

**What the community liked about Huntarr** (and wants in a replacement):
- Simple "missing content hunting" — conservative defaults (1 item every 15 minutes)
- Multi-instance support with independent schedules per instance
- Storage awareness — auto-pause when disk is low
- Sort options for which missing items to search first (newest/oldest)
- Lightweight Docker container alongside existing *arr stack

**What the community rejected:**
- Scope creep into replacing the entire *arr stack (built-in Radarr alternative, Prowlarr alternative, NZB client)
- Telemetry and obfuscated code
- No transparency, no code review, no security practices

**Splintarr's positioning:** Fill the same core gap (scheduled backlog searching) with the security practices and transparency that Huntarr lacked. Stay focused on search automation — don't try to replace the *arr apps. The README's AI-generated code disclaimer and the comprehensive security documentation are direct responses to this community concern.

---

## Feature Status

| # | Feature | Status | Release | Notes |
|---|---------|--------|---------|-------|
| 1 | [Library Overview](#1-library-overview) | **Done** | v0.1.0 | PRs #37-40 |
| 2 | [Content Exclusion Lists](#2-content-exclusion-lists) | **Done** | v0.2.0 | PR #63 |
| 7 | [Discord Notifications](#7-discord-notifications) | **Done** | v0.2.0 | PR #62 |
| - | [v0.2.0 Bug Fixes & UX Polish](#bug-fixes-from-v020-e2e-testing) | **Done** | v0.2.1 | PRs #70, #72; issues #65-#67 closed |
| 3 | [Health Monitoring & Auto-Recovery](#3-health-monitoring--auto-recovery) | **Done** | v0.2.1 | PR #74 |
| 4 | [Clone Queue & Presets](#4-clone-queue--presets) | **Done** | v0.2.1 | PR #75 |
| 5 | [Enhanced Activity Polling](#5-enhanced-activity-polling) | **Done** | v0.2.1 | PR #77; WebSocket deferred to v0.4.0+ |
| 6 | [Config Export & Integrity Check](#6-config-export--integrity-check) | **Done** | v0.2.1 | PR #76 |
| 10 | [Adaptive Search Prioritization](#10-adaptive-search-prioritization) | **Done** | v0.3.0 | PR #78 |
| 11 | [Search Cooldown Intelligence](#11-search-cooldown-intelligence) | **Done** | v0.3.0 | PR #79 |
| 12 | [Search Result Feedback Loop](#12-search-result-feedback-loop) | **Done** | v0.3.0 | PR #80 |
| 8 | [Prowlarr Integration](#8-prowlarr-integration) | Planned | v0.3.1 | Indexer-aware rate limiting |
| 9 | [Season Pack Intelligence](#9-season-pack-intelligence) | Planned | v0.3.1 | Sonarr only |
| 13 | [Search Analytics Dashboard](#13-search-analytics-dashboard) | Deferred | v0.4.0+ | |
| 14 | [Config Import](#14-config-import) | Deferred | v0.4.0+ | Companion to Config Export |
| 15 | [WebSocket Activity Feed](#15-websocket-real-time-activity-feed) | Deferred | v0.4.0+ | Upgrade from polling |

---

## Implemented Features

### v0.1.0

- **Library Overview** (PRs #37-40) — Poster grid, missing content view, per-item detail with episode breakdown. Background sync every 6h. Poster cache.

### v0.2.0

- **Content Exclusion Lists** (PR #63) — Per-item exclusions with expiration (permanent, 7/30/90 days). Exclusion management page, bulk exclude, library badge. [Spec →](#2-content-exclusion-lists)
- **Discord Notifications** (PR #62) — Fernet-encrypted webhook, per-event toggles, rich embeds, batched summaries, test button. [Spec →](#7-discord-notifications)
- **Gold/Maroon Rebrand** (PR #69) — New triple-ring logo and color scheme. Screenshots updated (PR #73).
- **Bug Fixes** (PRs #70, #72) — Setup wizard login timestamp (#67), mobile sidebar (#65), notification 404 (#66).

### v0.2.1

- **Health Monitoring & Auto-Recovery** (PR #74) — Periodic health checks (default 5 min), auto-pause/resume queues, Discord notifications on transitions, dashboard health indicators. [Spec →](#3-health-monitoring--auto-recovery)
- **Clone Queue & Presets** (PR #75) — Clone button pre-fills Create modal. Three built-in presets (Aggressive Missing, Weekly Cutoff, New Releases). [Spec →](#4-clone-queue--presets)
- **Enhanced Activity Polling** (PR #77) — Activity table live-updates every 15s, system status poll reduced to 30s, clear filters on Library/Exclusions. [Spec →](#5-enhanced-activity-polling)
- **Config Export & Integrity Check** (PR #76) — JSON config download (secrets redacted), PRAGMA integrity check, settings accordion, toast notifications. [Spec →](#6-config-export--integrity-check)

### v0.3.0

- **Adaptive Search Prioritization** (PR #78) — Scoring engine (recency/attempts/staleness, strategy-aware weights), items scored 0-100, sort by priority, max_items_per_run batch limit. [Spec →](#10-adaptive-search-prioritization)
- **Search Cooldown Intelligence** (PR #79) — DB-backed tiered cooldowns (6h to 7d by item age), exponential backoff (capped at 14 days), per-queue adaptive/flat mode. [Spec →](#11-search-cooldown-intelligence)
- **Search Result Feedback Loop** (PR #80) — Post-search command polling (15 min delay), grab detection, LibraryItem.grabs_confirmed tracking, dashboard grab rate. [Spec →](#12-search-result-feedback-loop)
- **Search Intelligence UI** (PR #81) — Score + reason in search logs, search stats on library detail, cooldown/batch config in queue modal, grab rate metric.

---

## v0.2.0 — Shipped

Two high-value, low-effort features that address the most immediate user needs.

### 2. Content Exclusion Lists

**Priority:** High | **Effort:** Low | **Status: Done** (PR #63, 2026-02-28)

**Problem:** Users have content they don't want searched — abandoned series, movies they don't care about upgrading, problematic releases. API calls are wasted on these items.

**User Stories:**
- *As a user browsing my library, I want to exclude a specific series or movie from all future searches with one click.*
- *As a user, I want temporary exclusions ("ignore for 30 days") for content I expect to become available later.*
- *As a user, I want to see all active exclusions in one place and remove them easily.*

**Requirements:**
- Exclude by library item ID (series/movie) with reason field
- Temporary exclusions with configurable expiration (7/30/90 days, or permanent)
- "Exclude" button on library detail page and in search results
- Exclusion management page: view all, filter by instance/type, remove
- Exclusions checked before search execution (skip excluded items, log as "skipped: excluded")
- Bulk exclude: select multiple items from library grid
- **Excluded items remain visible in the library** with an "excluded" badge — search-only exclusion, not hidden from view

**Data model:** New `search_exclusions` table (id, instance_id, library_item_id, external_id, content_type, title, reason, expires_at, created_at)

### 7. Discord Notifications

**Priority:** High | **Effort:** Low | **Status: Done** (PR #62, 2026-02-28)

**Problem:** No way to know when searches find content or fail without checking the dashboard.

**User Stories:**
- *As a user, I want a Discord message when a search finds and grabs new content.*
- *As a user, I want alerts when a queue fails repeatedly or an instance goes down.*
- *As a user, I do NOT want notifications for routine empty searches — only meaningful events.*

**Requirements:**
- Discord webhook URL configuration in Settings
- Event types (each independently toggleable): content grabbed, queue failed, instance lost/recovered, library sync completed
- Rich Discord embeds: poster thumbnail, item title, quality, instance name
- **Batched notifications**: one summary embed per search run (not per item) to prevent spam
- Rate limit: max 1 notification per event type per 5 minutes
- Test button in settings to verify webhook connectivity

**Data model:** New `notification_config` table (id, webhook_url_encrypted, events_enabled_json, is_active, last_sent_at)

---

## v0.2.1 — Shipped

Operational improvements, debugging tools, and UX polish from v0.2.0 E2E testing.

### Bug Fixes from v0.2.0 E2E Testing

**Status: Done** (PRs #70, #72)

All three bugs identified during E2E testing are closed:

- ~~**Mobile sidebar conflict** ([#65](https://github.com/menottim/splintarr/issues/65))~~ — Verified correct: CSS already uses `translateX(-100%)` on mobile; old collapsed-icon rules already removed. No code change needed.
- ~~**Notification config 404 on first load** ([#66](https://github.com/menottim/splintarr/issues/66))~~ — Verified correct: JS already handles 404 gracefully (`response.ok` check + `try/catch`). Browser console network error is expected, not a bug.
- ~~**"Last Login: Never" after setup wizard** ([#67](https://github.com/menottim/splintarr/issues/67))~~ — Fixed: calls `record_successful_login()` after account creation in setup wizard (PR #70, method name corrected in PR #72).

### UX Polish

- **Settings page organization** — Settings is getting long with Account, Password, 2FA, Notifications, and Danger Zone sections. Consider tabs or collapsible accordion sections.
- **Filter UX** — Add "Clear filters" button to Library and Exclusions filter dropdowns
- **Notification save feedback** — Add loading state to "Save" button in notification settings (disable + spinner while saving)
- **Quick Actions consistency** — "Browse Library" link in dashboard Quick Actions should be visually styled the same as other links (underline/color)

### 3. Health Monitoring & Auto-Recovery

**Priority:** High | **Effort:** Medium | **Status: Done** (PR #74, 2026-02-28)

**Problem:** When a Sonarr/Radarr instance goes down, queues fail silently until the user notices. The current 5-failure auto-deactivation burns through the failure budget and doesn't auto-recover.

**Requirements:**
- Periodic health checks: ping each instance every N minutes (configurable, default 5)
- **Connectivity check only** (`/api/v3/system/status`) — fast and low overhead. API key validity tested when searches run.
- Auto-pause queues when instance is unreachable (instead of burning through failure budget)
- Auto-resume queues when instance recovers, with a backoff period
- Dashboard health indicator: green/yellow/red per instance

**Data model:** Lean columns on Instance (consecutive_failures, consecutive_successes, last_healthy_at, response_time_ms) instead of a dedicated history table. Config: `HEALTH_CHECK_INTERVAL_MINUTES` (default 5), `HEALTH_CHECK_RECOVERY_THRESHOLD` (default 2).

### 4. Clone Queue & Presets

**Priority:** Medium | **Effort:** Low | **Status: Done** (PR #75, 2026-02-28)

*Simplified from the original "Search Profiles & Templates" feature. A full profiles system is overengineered for 1-5 instances.*

**Problem:** Creating search queues is repetitive with multiple instances. Same strategy, same interval — configured manually each time.

**Requirements:**
- "Clone" button on existing queues (copies all settings, user changes instance/name)
- Built-in presets in the Create Queue modal: "Aggressive Missing" (hourly), "Weekly Cutoff Unmet" (weekly), "New Releases" (every 4h)
- Selecting a preset pre-fills the form fields (user can override before creating)
- No separate profiles table — presets are hardcoded, cloning uses the existing queue data

### 5. Enhanced Activity Polling

**Priority:** Medium | **Effort:** Low | **Status: Done** (PR #77, 2026-02-28)

*Simplified from the original "Real-Time Activity Feed" feature. Full WebSocket deferred to [Feature 15](#15-websocket-real-time-activity-feed).*

**Problem:** Dashboard uses AJAX polling (30s) for stats and system status, but the Recent Search Activity table is server-rendered and never updates without a page refresh. The `/api/dashboard/activity` endpoint exists but is unused.

**Requirements:**
- Wire up `/api/dashboard/activity` to poll every 15 seconds
- Live-update the Recent Search Activity table via JS DOM manipulation
- Reduce system status polling from 60s to 30s
- Add "Clear filters" button to Library and Exclusions filter dropdowns

### 6. Config Export & Integrity Check

**Priority:** Medium | **Effort:** Low | **Status: Done** (PR #76, 2026-02-28)

*Simplified from the original "Backup & Restore" feature. User handles Docker volume backups externally.*

**Problem:** No way to export configuration or verify database integrity.

**Requirements:**
- Configuration export as JSON from settings page (instances, queues, settings — API keys excluded)
- Database integrity check: run `PRAGMA integrity_check` on demand from settings page
- Display last integrity check result and database file size
- No scheduled backups, no restore wizard, no backup retention — user's external backup system handles the data volume

---

## v0.3.0 — Shipped

The core differentiator: making searches smarter, not just scheduled.

### 10. Adaptive Search Prioritization

**Priority:** High | **Effort:** Medium | **Status: Done** (PR #78, 2026-03-01)

**Problem:** Fixed ordering wastes API calls on unfindable content. Recently aired content waits behind years-old missing episodes. [Known gap](https://github.com/Sonarr/Sonarr/issues/3067).

**User Stories:**
- *Recently aired content prioritized (most likely available).*
- *Items searched 20+ times with no results automatically deprioritized.*
- *I can see why an item was prioritized/deprioritized in the search log.*

**Requirements:**
- Score each item before searching based on: recency, search history (failed attempts), time since last search
- Strategy-specific scoring:
  - Missing: weight recency (air date) and total search attempts
  - Cutoff Unmet: weight quality gap (how far below cutoff) and time since last upgrade
- **Scores visible** in search logs and library detail page — full transparency per design principle
- Sort the search queue by score before executing

**Data model:** Add `search_attempts`, `last_searched_at` to `library_items`

### 11. Search Cooldown Intelligence

**Priority:** Medium | **Effort:** Low | **Status: Done** (PR #79, 2026-03-01) | **Depends on:** #10

**Problem:** 24-hour flat cooldown is a blunt instrument. Fresh content needs more frequent searching; old content needs less.

**Requirements:**
- **Conservative tiered cooldowns** (gentler on indexers than originally proposed):
  - Aired/added within 24 hours: 6-hour cooldown
  - Aired/added within 7 days: 12-hour cooldown
  - Aired/added within 30 days: 24-hour cooldown
  - Aired/added 30+ days ago: 72-hour cooldown
  - Aired/added 1+ year ago: 7-day cooldown
- Exponential backoff for repeated failures: each consecutive search with no result doubles the cooldown (capped at 14 days)
- Reset cooldown when: content is newly aired, quality profile changes, or user manually triggers search
- Configurable: allow users to override with a flat cooldown if they prefer simplicity

### 12. Search Result Feedback Loop

**Priority:** Medium | **Effort:** Medium | **Status: Done** (PR #80, 2026-03-01)

**Problem:** Splintarr records "search sent" but not whether anything was grabbed. True success rates unknown.

**Requirements:**
- After triggering a search, poll the item's status after a configurable delay (default: 15 minutes) to detect grabs
- Track per-item: searches_triggered, grabs_confirmed, last_grab_at
- Feed grab data into adaptive prioritization (#10) and cooldown intelligence (#11)
- Dashboard metric: actual grab rate vs search rate

**Data model:** Add `grabs_confirmed`, `last_grab_at` to `library_items`. Add `grab_confirmed` to search_log.

---

## v0.3.1 — Search Intelligence: External Integrations

### 8. Prowlarr Integration & Indexer-Aware Rate Limiting

**Priority:** High | **Effort:** Medium | **Status:** Planned

**Problem:** Blanket per-instance rate limit doesn't account for individual indexer API limits. Being too aggressive gets you banned; too conservative means missing content.

**User Stories:**
- *As a Prowlarr user, I want Splintarr to read my indexer configurations and respect each indexer's API limits.*
- *As a user, I want to see indexer health and API usage on the dashboard.*

**Requirements:**
- Connect to Prowlarr API (URL + API key, same pattern as Sonarr/Radarr instances)
- Read indexer list with capabilities and API limits
- Map indexers to Sonarr/Radarr instances (Prowlarr knows which indexers sync to which apps)
- Calculate effective rate limit per instance based on most restrictive connected indexer
- Track API call count per indexer per time window (hourly/daily)
- Dashboard widget showing indexer health and usage
- Fallback: if Prowlarr not configured, use existing per-instance rate limit

**Data model:** New `prowlarr_config`, `indexers`, `indexer_usage` tables

### 9. Season Pack Intelligence (Sonarr Only)

**Priority:** High | **Effort:** Medium | **Status:** Planned

**Problem:** Individual episode searches fail for older content where only season packs exist. Wastes API calls. [Most requested Sonarr feature](https://github.com/Sonarr/Sonarr/issues/4229).

**User Stories:**
- *When 3+ episodes from the same season are missing, try a season pack search before per-episode.*
- *Cutoff unmet season packs should only upgrade quality, not re-download deleted episodes.*

**Requirements:**
- Before per-episode searching, group missing episodes by series + season
- If N+ missing (configurable, default 3), issue `SeasonSearch` command instead of individual `EpisodeSearch`
- Strategy isolation: both Missing and Cutoff Unmet strategies use `SeasonSearch`, which respects monitored status and quality profile in Sonarr
- Configurable: enable/disable season pack mode per queue
- Sonarr-only — Radarr has no equivalent (movies are single items)

---

## v0.4.0+ — Deferred

### 13. Search Analytics Dashboard

**Priority:** Low | **Effort:** Medium | **Status:** Deferred

Time-series charts, strategy comparison, instance comparison. Lightweight chart library bundled locally (no CDN). Useful for occasional glancing but not a daily need.

### 14. Config Import

**Priority:** Low | **Effort:** Medium | **Status:** Deferred

Companion to Config Export (v0.2.1). Upload a previously exported JSON file to re-create instances, queues, exclusions, and notification settings. Requires conflict resolution (duplicate names, missing API keys that must be re-entered). Not needed for v0.2.1 — export is reference/documentation material for now.

### 15. WebSocket Real-Time Activity Feed

**Priority:** Low | **Effort:** Medium | **Status:** Deferred

Upgrade the v0.2.1 enhanced polling (15s interval) to true WebSocket push at `/ws/activity`. In-process event bus, connection registry, graceful fallback to polling, JWT cookie auth on WS upgrade, reconnect logic for 15-min token expiry. Deferred because enhanced polling provides 80% of the value for a single-user homelab app.

---

## Open Questions

| # | Question | Context |
|---|----------|---------|
| 1 | Prowlarr API stability | Less documented than Sonarr/Radarr. Need to verify indexer rate limit fields are available. |
| 2 | Season pack threshold | Default 3+ missing. Configurable per queue or global? |

---

## Resolved Decisions

| Decision | Resolution | Date |
|----------|------------|------|
| Poster storage | Local cache in `data/posters/` | 2026-02-27 |
| Library sync frequency | Default 6 hours, configurable | 2026-02-27 |
| Episode granularity | Per-episode for Sonarr, item-level for Radarr | 2026-02-27 |
| Quality profile display | Store ID for now | 2026-02-27 |
| Notification channel | Discord webhook as primary | 2026-02-28 |
| Strategy isolation | Missing and Cutoff Unmet never combined | 2026-02-28 |
| Exclusion scope | Search-only — items stay visible in library with badge | 2026-02-28 |
| Health check depth | Connectivity only (/system/status) | 2026-02-28 |
| Notification batching | One summary embed per search run, not per item | 2026-02-28 |
| Search Profiles | Simplified to Clone Queue + built-in presets in modal | 2026-02-28 |
| Backup & Restore | Simplified to Config Export + Integrity Check (user handles volumes) | 2026-02-28 |
| Cooldown defaults | Conservative — gentler on indexers (6h/12h/24h/72h/7d) | 2026-02-28 |
| Priority transparency | Scores visible in search logs and library detail | 2026-02-28 |
| v0.2.0 scope | Exclusion Lists + Discord Notifications only | 2026-02-28 |
| v0.2.1 scope | Health Monitoring moved here from v0.2.0 | 2026-02-28 |
| v0.3 split | v0.3.0 = core algorithm, v0.3.1 = Prowlarr + Season Packs | 2026-02-28 |
| Bug #65 (mobile sidebar) | Verified correct — no code change needed | 2026-02-28 |
| Bug #66 (notification 404) | Verified correct — browser console error, not a bug | 2026-02-28 |
| Bug #67 (last login) | Fixed — `record_successful_login()` in setup wizard | 2026-02-28 |
| PRD-v0.2.md | Deprecated and removed from repo; unified PRD is sole source of truth | 2026-02-28 |
| Scoring data source | API response enriched with DB history (always search what *arr says is missing) | 2026-03-01 |
| Scoring architecture | Unified scorer with strategy-aware weights (not separate scorers) | 2026-03-01 |
| Cooldown persistence | DB-backed (LibraryItem columns), not in-memory | 2026-03-01 |
| Cooldown granularity | Per-queue (adaptive or flat mode) | 2026-03-01 |
| Grab detection | Poll command status after configurable delay (default 15 min) | 2026-03-01 |
| Batch limits | Per-queue max_items_per_run (default 50) | 2026-03-01 |
| Fetch strategy | Fetch all wanted items from API, accept read cost for accurate scoring | 2026-03-01 |
| Feedback loop delay | 15 min default, configurable 5-60 min | 2026-03-01 |

---

## Document History

| Date | Change |
|------|--------|
| 2026-02-26 | PRD v0.2 created with Features 1-9 |
| 2026-02-27 | Feature 1 (Library Overview) implemented (PRs #37-40) |
| 2026-02-28 | Features 10-12 proposed based on community research |
| 2026-02-28 | Merged into unified ongoing PRD; versioned PRDs archived |
| 2026-02-28 | Huntarr incident context added (security vulnerabilities, community response) |
| 2026-02-28 | Feature walkthrough: simplified #4, #6; reordered releases; resolved 11 open questions |
| 2026-02-28 | v0.2.0 shipped: Exclusion Lists (PR #63) + Discord Notifications (PR #62) |
| 2026-02-28 | Gold/maroon rebrand (PR #69), screenshots updated (PR #73) |
| 2026-02-28 | v0.2.0 bug fixes resolved: #65-#67 all closed (PRs #70, #72) |
| 2026-02-28 | PRD updated to reflect all shipped work; `PRD-v0.2.md` archived (deleted from repo) |
| 2026-02-28 | v0.2.1 shipped: Health Monitoring (#74), Clone/Presets (#75), Config Export (#76), Activity Polling (#77) |
| 2026-03-01 | v0.3.0 shipped: Scoring (#78), Tiered Cooldowns (#79), Feedback Loop (#80), Intelligence UI (#81) |
