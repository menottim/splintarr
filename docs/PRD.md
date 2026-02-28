# Splintarr — Product Requirements Document

> **Living document.** Updated as features are implemented, priorities shift, or new requirements emerge. Previous versioned PRDs are archived in `docs/plans/`.

**Last updated:** 2026-02-28

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
| 1 | [Library Overview](#1-library-overview) | Done | v0.1.0 | PRs #37-40 |
| 2 | [Content Exclusion Lists](#2-content-exclusion-lists) | Planned | v0.2.0 | High priority, user-requested |
| 3 | [Health Monitoring & Auto-Recovery](#3-health-monitoring--auto-recovery) | Planned | v0.2.0 | |
| 4 | [Search Profiles & Templates](#4-search-profiles--templates) | Planned | v0.2.1 | |
| 5 | [Real-Time Activity Feed](#5-real-time-activity-feed) | Planned | v0.2.1 | |
| 6 | [Backup & Restore](#6-backup--restore) | Planned | v0.2.1 | |
| 7 | [Discord Notifications](#7-discord-notifications) | Planned | v0.2.0 | High priority, user-requested |
| 8 | [Prowlarr Integration](#8-prowlarr-integration) | Planned | v0.3.0 | Enables indexer-aware rate limiting |
| 9 | [Season Pack Intelligence](#9-season-pack-intelligence) | Planned | v0.3.0 | Sonarr only |
| 10 | [Adaptive Search Prioritization](#10-adaptive-search-prioritization) | Planned | v0.3.0 | Core search intelligence |
| 11 | [Search Cooldown Intelligence](#11-search-cooldown-intelligence) | Planned | v0.3.0 | Builds on #10 |
| 12 | [Search Result Feedback Loop](#12-search-result-feedback-loop) | Planned | v0.3.0 | Closes the learning loop |
| 13 | [Search Analytics Dashboard](#13-search-analytics-dashboard) | Deferred | v0.4.0+ | |

---

## Implemented Features

### 1. Library Overview

**Status: Done** (PRs #37-40, 2026-02-27)

Pulls and caches series/movie data from connected Sonarr/Radarr instances. Poster grid, missing content view, per-item detail with episode breakdown. Background sync every 6 hours (configurable). Poster images cached locally.

**Resolved decisions:** Local poster cache (not proxy). Per-episode tracking for Sonarr. Quality profile stored as ID.

---

## v0.2.0 — Ship First

### 2. Content Exclusion Lists

**Priority:** High | **Effort:** Low | **Status:** Planned

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

**Data model:** New `search_exclusions` table (id, instance_id, library_item_id, external_id, content_type, title, reason, expires_at, created_at)

### 3. Health Monitoring & Auto-Recovery

**Priority:** High | **Effort:** Medium | **Status:** Planned

**Problem:** When a Sonarr/Radarr instance goes down, queues fail silently until the user notices. The current 5-failure auto-deactivation burns through the failure budget and doesn't auto-recover.

**Requirements:**
- Periodic health checks: ping each instance every N minutes (configurable, default 5)
- Auto-pause queues when instance is unreachable (instead of burning through failure budget)
- Auto-resume queues when instance recovers, with a backoff period
- Dashboard health indicator: green/yellow/red per instance
- Connection quality metrics: response time, timeout rate, error rate over 24h

**Data model:** New `health_checks` table (instance_id, checked_at, success, response_time_ms, error_message). Add `health_check_interval_minutes` to `instances`.

### 7. Discord Notifications

**Priority:** High | **Effort:** Low | **Status:** Planned

**Problem:** No way to know when searches find content or fail without checking the dashboard.

**User Stories:**
- *As a user, I want a Discord message when a search finds and grabs new content.*
- *As a user, I want alerts when a queue fails repeatedly or an instance goes down.*
- *As a user, I do NOT want notifications for routine empty searches — only meaningful events.*

**Requirements:**
- Discord webhook URL configuration in Settings
- Event types (each independently toggleable): content grabbed, queue failed, instance lost/recovered, library sync completed
- Rich Discord embeds: poster thumbnail, item title, quality, instance name
- Rate limit: max 1 notification per event type per 5 minutes (prevent spam)
- Test button in settings to verify webhook connectivity

**Data model:** New `notification_config` table (id, webhook_url_encrypted, events_enabled_json, is_active, last_sent_at)

---

## v0.2.1 — Ship Next

### 4. Search Profiles & Templates

**Priority:** Medium | **Effort:** Low | **Status:** Planned

**Problem:** Creating search queues is repetitive with 3-5 instances. Same strategy, same interval — configured manually each time.

**Requirements:**
- Save queue configuration as reusable template
- Built-in defaults: "Aggressive Missing" (hourly), "Weekly Cutoff Unmet" (weekly), "New Releases" (every 4h)
- Apply template to multiple instances at once (batch queue creation)
- Clone existing queue as starting point

**Data model:** New `search_profiles` table (id, user_id, name, strategy, interval_hours, filters, is_builtin, created_at)

### 5. Real-Time Activity Feed

**Priority:** Medium | **Effort:** Medium | **Status:** Planned

**Problem:** Dashboard uses AJAX polling (30s). Delay between action and result. Live progress would aid debugging.

**Requirements:**
- WebSocket at `/ws/activity` for real-time updates
- Events: search started/completed/failed, instance health changed, queue status changed
- Graceful fallback to polling if WebSocket fails
- Connection indicator in dashboard header
- Per-search live progress: items scanned / total

### 6. Backup & Restore

**Priority:** Medium | **Effort:** Low | **Status:** Planned

**Problem:** Encrypted database is a single point of failure. No recovery mechanism.

**Requirements:**
- Full backup downloadable from settings
- Scheduled automatic backups: daily, keep last N (default 7)
- Restore wizard with integrity verification
- Configuration-only export as JSON (API keys excluded)

**Data model:** New `backups` table (id, backup_type, file_path, file_size, created_at, status)

---

## v0.3.0 — Search Intelligence

The core differentiator: making searches smarter, not just scheduled.

### 8. Prowlarr Integration & Indexer-Aware Rate Limiting

**Priority:** High | **Effort:** Medium | **Status:** Planned

**Problem:** Blanket per-instance rate limit doesn't account for individual indexer API limits. Being too aggressive gets you banned; too conservative means missing content.

**User Stories:**
- *As a Prowlarr user, I want Splintarr to read my indexer configurations and respect each indexer's API limits.*
- *As a user, I want to see indexer health and usage on the dashboard.*

**Requirements:**
- Connect to Prowlarr API (URL + API key)
- Read indexer list with capabilities and API limits
- Map indexers to Sonarr/Radarr instances
- Calculate effective rate limit per instance based on most restrictive indexer
- Track API call count per indexer per time window
- Fallback: if Prowlarr not configured, use existing per-instance rate limit

**Data model:** New `prowlarr_config`, `indexers`, `indexer_usage` tables

### 9. Season Pack Intelligence (Sonarr Only)

**Priority:** High | **Effort:** Medium | **Status:** Planned

**Problem:** Individual episode searches fail for older content where only season packs exist. Wastes API calls. [Most requested Sonarr feature](https://github.com/Sonarr/Sonarr/issues/4229).

**User Stories:**
- *When 3+ episodes from the same season are missing, try a season pack search before per-episode.*
- *Cutoff unmet season packs should only upgrade quality, not re-download deleted episodes.*

**Requirements:**
- Group missing episodes by series + season before searching
- If N+ missing (configurable, default 3), issue `SeasonSearch` instead of `EpisodeSearch`
- Strategy isolation: both strategies use `SeasonSearch` but Sonarr respects monitored status and quality profile
- Configurable: enable/disable per queue

### 10. Adaptive Search Prioritization

**Priority:** High | **Effort:** Medium | **Status:** Planned

**Problem:** Fixed ordering wastes API calls on unfindable content. Recently aired content waits behind years-old missing episodes. [Known gap](https://github.com/Sonarr/Sonarr/issues/3067).

**User Stories:**
- *Recently aired content prioritized (most likely available).*
- *Items searched 20+ times with no results automatically deprioritized.*
- *I can see why an item was prioritized/deprioritized in the search log.*

**Requirements:**
- Score items by: recency, search history (failed attempts), time since last search
- Strategy-specific: Missing weights air date; Cutoff Unmet weights quality gap
- Log score in search_metadata for transparency

**Data model:** Add `search_attempts`, `last_searched_at` to `library_items`

### 11. Search Cooldown Intelligence

**Priority:** Medium | **Effort:** Low | **Status:** Planned | **Depends on:** #10

**Problem:** 24-hour flat cooldown is a blunt instrument. Fresh content needs aggressive searching; old content needs less.

**Requirements:**
- Tiered cooldowns: 2h (just aired) → 6h (this week) → 24h (this month) → 72h (older) → 7d (1yr+)
- Exponential backoff for repeated failures (capped at 14 days)
- Reset on: new air date, quality profile change, manual trigger

### 12. Search Result Feedback Loop

**Priority:** Medium | **Effort:** Medium | **Status:** Planned

**Problem:** Splintarr records "search sent" but not whether anything was grabbed. True success rates unknown.

**Requirements:**
- Poll item status after configurable delay (default 15 min) to detect grabs
- Track per-item: searches_triggered, grabs_confirmed, last_grab_at
- Feed into adaptive prioritization and cooldown intelligence
- Dashboard metric: actual grab rate vs search rate

**Data model:** Add `grabs_confirmed`, `last_grab_at` to `library_items`. Add `grab_confirmed` to search_log.

---

## v0.4.0+ — Deferred

### 13. Search Analytics Dashboard

**Priority:** Low | **Effort:** Medium | **Status:** Deferred

Time-series charts, strategy comparison, instance comparison. Lightweight chart library bundled locally (no CDN).

---

## Open Questions

| # | Question | Context |
|---|----------|---------|
| 1 | Prowlarr API stability | Less documented than Sonarr/Radarr. Need to verify indexer rate limit fields. |
| 2 | Season pack threshold | Default 3+ missing. Configurable per queue or global? |
| 3 | Feedback loop delay | 15 min between search and status check — right balance? |
| 4 | Notification batching | Batch 20 grabs into 1 Discord message, or send individually? |
| 5 | Exclusion scope | Exclude from searches only, or also from library sync? |
| 6 | Health check scope | Test just connectivity, or also API key validity and config drift? |

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

---

## Document History

| Date | Change |
|------|--------|
| 2026-02-26 | PRD v0.2 created with Features 1-9 |
| 2026-02-27 | Feature 1 (Library Overview) implemented |
| 2026-02-28 | Features 10-15 proposed based on community research |
| 2026-02-28 | Merged into unified ongoing PRD; versioned PRDs archived |
