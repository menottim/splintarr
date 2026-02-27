# Splintarr v0.2 — Product Requirements Document

## Current State (v0.1.0-alpha)

Splintarr is a Docker-first homelab application that automates intelligent backlog searching for Sonarr and Radarr instances. It currently provides:

- Multi-instance Sonarr/Radarr management with encrypted API keys
- 4 automated search strategies (missing, cutoff_unmet, recent, custom)
- Background job scheduling via APScheduler
- JWT authentication with 2FA (TOTP), account lockout, token rotation
- SQLCipher-encrypted database
- Server-rendered dashboard with Pico CSS
- Search history tracking and statistics
- CLI for admin password resets

## Proposed Features for v0.2

---

### Feature 1: Webhook Notifications

**Priority:** High
**Effort:** Medium

**Problem:** Users have no way to know when searches complete, fail, or find content without checking the dashboard. In a homelab context, the dashboard isn't always open.

**Requirements:**
- Support Discord, Slack, and generic HTTP webhook targets
- Configurable notification events: search completed, search failed, new content found, queue paused (consecutive failures), instance connection lost
- Per-instance or global notification preferences
- Notification payload includes: search name, strategy, items found, instance name, timestamp
- Test webhook button in settings UI
- Respect rate limits on notification delivery (batch if >5 events/minute)

**Data model changes:** New `notification_channels` table (id, user_id, channel_type, webhook_url, events_filter, is_active, created_at)

---

### Feature 2: Smart Search Scheduling

**Priority:** High
**Effort:** Medium

**Problem:** The current scheduler uses fixed intervals (e.g., every 24 hours). This is wasteful for shows with known release schedules and insufficient for newly-aired content that benefits from immediate searching.

**Requirements:**
- Calendar-aware scheduling: allow specifying day-of-week and time windows (e.g., "Fridays 6pm-10pm" for weekly anime)
- Blackout windows: prevent searches during specified hours (e.g., don't search 2am-6am when seeders are low)
- Adaptive intervals: automatically increase search frequency when a show has a new episode airing (based on Sonarr calendar data), decrease during off-season
- Burst mode: option to run searches every N minutes for the first X hours after an episode airs, then fall back to normal interval
- Retain the simple "every X hours" option as default for users who don't want complexity

**Data model changes:** Extend `search_queue` with `schedule_type` (interval|calendar|adaptive), `schedule_config` (JSON with day/time rules), `blackout_windows` (JSON array)

---

### Feature 3: Search Analytics Dashboard

**Priority:** Medium
**Effort:** Medium

**Problem:** The current dashboard shows basic counts (searches today, this week, success rate) but provides no insight into trends, performance by strategy, or which instances are most/least effective.

**Requirements:**
- Time-series charts: searches over time (daily/weekly/monthly), success rate trend, items found trend
- Strategy comparison: which strategy finds the most content, average items per run by strategy
- Instance comparison: which instances have the best hit rate, slowest response times
- Search efficiency metrics: average time to find content after it airs, search-to-find ratio
- Export data as CSV for external analysis
- Responsive charts using a lightweight library (Chart.js or similar, loaded from static assets — no CDN for homelab privacy)

**Data model changes:** None — derived from existing `search_history` table. May add materialized views or summary tables for performance.

---

### Feature 4: Multi-User with Role-Based Access

**Priority:** Medium
**Effort:** High

**Problem:** The framework for multi-user exists (user_id foreign keys, instance ownership) but there's no user management UI, no role system, and some operations lack proper tenant isolation (recently fixed for cleanup).

**Requirements:**
- Admin panel: create/edit/disable/delete user accounts
- Three roles: Admin (full access), Operator (manage own instances/queues, view shared), Viewer (read-only dashboard)
- Instance sharing: admin can grant other users access to specific instances (read-only or read-write)
- Shared queues: search queues visible across users who share the instance, with edit restricted to owner/admin
- Activity audit log: track who did what (created instance, started search, changed settings) with timestamps
- Admin can impersonate users for support

**Data model changes:** New `roles` table, new `instance_shares` table (instance_id, user_id, permission_level), new `audit_log` table

---

### Feature 5: Sonarr/Radarr Sync & Library Overview

**Priority:** High
**Effort:** Medium

**Problem:** Users can't see what's in their Sonarr/Radarr libraries from within Splintarr. They must switch between apps to understand what's missing and what's been found.

**Requirements:**
- Pull and cache series/movie lists from connected instances
- Library overview page: total series/movies, percent complete, recently added
- Per-series/movie detail: which episodes are missing, quality status, last searched date
- "Missing content" view: aggregated list across all instances of what hasn't been found
- Refresh button and configurable auto-sync interval (default: every 6 hours)
- Show series poster art (cached locally from instance)

**Data model changes:** New `library_cache` table (instance_id, content_type, content_id, title, metadata_json, last_synced_at). Consider a separate `library_items` table for normalized data.

---

### Feature 6: Search Profiles & Templates

**Priority:** Medium
**Effort:** Low

**Problem:** Creating search queues requires manually configuring strategy, interval, and filters each time. Users with many instances or similar configurations repeat the same setup.

**Requirements:**
- Search profile templates: save a queue configuration as a reusable template
- Built-in defaults: "Aggressive Missing" (hourly, missing strategy), "Weekly Upgrade" (weekly, cutoff_unmet), "New Releases" (every 4 hours, recent)
- Apply template to multiple instances at once (batch queue creation)
- Import/export profiles as JSON for sharing between Splintarr installations
- Clone existing queue as a starting point for a new one

**Data model changes:** New `search_profiles` table (id, user_id, name, strategy, interval_hours, filters, is_builtin, created_at)

---

### Feature 7: Health Monitoring & Auto-Recovery

**Priority:** High
**Effort:** Medium

**Problem:** When a Sonarr/Radarr instance goes down, queues fail silently until the user notices. The current 5-failure auto-deactivation helps but doesn't recover when the instance comes back.

**Requirements:**
- Periodic health checks: ping each instance every N minutes (configurable, default 5)
- Health status timeline: show uptime/downtime history per instance
- Auto-pause queues when instance is unreachable (instead of burning through failure budget)
- Auto-resume queues when instance recovers, with a backoff period
- Connection quality metrics: average response time, timeout rate, error rate over last 24h
- Dashboard health indicator: green/yellow/red per instance with tooltip showing last check time and latency

**Data model changes:** New `health_checks` table (instance_id, checked_at, success, response_time_ms, error_message). Add `health_check_interval_minutes` to `instances`.

---

### Feature 8: Content Exclusion Lists

**Priority:** Medium
**Effort:** Low

**Problem:** Users may want to exclude certain series, movies, or episodes from automated searches (e.g., shows they've abandoned, movies they don't care about upgrading, problematic releases).

**Requirements:**
- Per-instance or global exclusion lists
- Exclude by: series/movie ID, title pattern (regex), quality profile, tag, genre
- Temporary exclusions with expiration date ("ignore for 30 days")
- Exclusion applies across all search strategies for the instance
- UI to manage exclusions: add from search results, bulk add, import from text file
- Audit trail: log when items are excluded/included with reason

**Data model changes:** New `search_exclusions` table (id, instance_id, exclusion_type, pattern, reason, expires_at, created_by, created_at)

---

### Feature 9: Real-Time Activity Feed with WebSocket

**Priority:** Low
**Effort:** Medium

**Problem:** The dashboard uses AJAX polling (every 30 seconds) for updates. This is inefficient and provides a poor user experience — there's always a delay between an action and seeing the result.

**Requirements:**
- WebSocket endpoint at `/ws/activity` for real-time updates
- Events streamed: search started, search completed, search failed, instance health changed, queue status changed
- Dashboard auto-updates without page refresh when WebSocket connected
- Graceful fallback to polling if WebSocket connection fails
- Connection indicator in dashboard header (green dot = live, grey = polling)
- Per-search live progress: items scanned / total, currently searching episode/movie name

**Technical notes:** FastAPI natively supports WebSocket. Use a simple in-process event bus (no need for Redis at single-worker scale).

---

### Feature 10: Backup, Restore & Configuration Export

**Priority:** Medium
**Effort:** Low

**Problem:** The SQLCipher-encrypted database is the single point of failure. There's no way to backup configuration, migrate to a new machine, or recover from database corruption.

**Requirements:**
- Full backup: encrypted database dump downloadable from settings page
- Configuration-only export: instances, queues, profiles, settings as JSON (API keys excluded by default, option to include encrypted)
- Configuration import: restore instances and queues from JSON export
- Scheduled automatic backups: daily, keep last N backups (configurable)
- Backup to external storage: local path (Docker volume), and optionally S3-compatible storage
- Restore wizard: upload backup file, verify integrity, restore
- Database integrity check: run `PRAGMA integrity_check` on demand

**Data model changes:** New `backups` table (id, backup_type, file_path, file_size, created_at, status). Add settings for backup schedule and retention.

---

## Implementation Priority Matrix

| Feature | Priority | Effort | Dependencies | Suggested Release |
|---------|----------|--------|-------------|-------------------|
| 1. Webhook Notifications | High | Medium | None | v0.2.0 |
| 5. Library Overview | High | Medium | None | v0.2.0 |
| 7. Health Monitoring | High | Medium | None | v0.2.0 |
| 2. Smart Scheduling | High | Medium | None | v0.2.0 |
| 10. Backup & Restore | Medium | Low | None | v0.2.0 |
| 6. Search Profiles | Medium | Low | None | v0.2.1 |
| 8. Exclusion Lists | Medium | Low | None | v0.2.1 |
| 3. Analytics Dashboard | Medium | Medium | Chart.js | v0.2.1 |
| 4. Multi-User RBAC | Medium | High | Audit log | v0.3.0 |
| 9. WebSocket Activity | Low | Medium | None | v0.3.0 |

## Open Questions

1. **Notification providers:** Should we support Apprise (meta-notification library) to get 80+ services for free, or build direct integrations for the top 3 (Discord, Slack, generic webhook)?
2. **Library sync frequency:** How often should we pull series/movie lists? This could be expensive for large libraries. Should we use Sonarr/Radarr webhooks instead of polling?
3. **Chart library:** Chart.js (~200KB) vs uPlot (~35KB) vs simple SVG charts? Homelab users may prefer minimal dependencies.
4. **Backup encryption:** Should config-only exports be encrypted? Users may want to edit the JSON, but API keys need protection.
5. **WebSocket auth:** Should the WebSocket use the same JWT cookie auth, or a separate connection token?
