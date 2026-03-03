# Release Manager Skill — Design Document

> **Date:** 2026-03-03
> **Status:** Approved — ready for implementation

## Problem

Release orchestration across multiple documentation files and repositories is repetitive, error-prone, and time-consuming. In the Splintarr v1.1.0 release cycle, we performed 3 release operations and still found 27 stale references in a post-release consistency audit. Each release touches 7+ files across 2 repos (main + wiki), requiring version bumps, feature list updates, release note writing, GitHub release creation, and cross-doc verification.

## Solution

A reusable Claude Code skill (`release-manager`) that handles the entire release lifecycle: discovery, version bump, doc updates, consistency audit, commit/push, GitHub release, and verification.

## Design

### Trigger & Inputs

- **Invocation:** Use when the user asks to cut a release, ship a version, or publish a new version.
- **Arguments:** Optional version string (e.g., `v1.2.0`). If omitted, the skill asks.
- **Skill type:** Rigid — checklist-driven, every phase runs in order.

### Phase 0: Context Discovery

Reads CLAUDE.md and auto-memory to find:
- **Version source** — scans for `pyproject.toml`, `package.json`, `Cargo.toml`, etc.
- **Release checklist** — looks for a "Release" or "Release checklist" section in CLAUDE.md
- **Doc files** — discovers README, RELEASE_NOTES, CHANGELOG, PRD, wiki repos
- **Git remotes** — checks for wiki repos, detects GitHub host

Falls back to asking the user if discovery fails, then saves to memory for next time.

### Phase 1: Pre-flight Check

- Verify clean git status (no uncommitted changes)
- Read current version from version source
- Ask user for new version (or confirm if passed as arg)
- Generate changelog from commits since last release tag (`git log --oneline <last-tag>..HEAD`)
- **Gate:** User confirms version number and changelog draft

### Phase 2: Version Bump (automated)

- Update version in discovered version source file(s)
- Update version references in README (badge/link)
- Write new release notes to RELEASE_NOTES file if it exists

### Phase 3: Documentation Updates (automated)

- For each discovered doc file, scan for version references and update
- If PRD/roadmap exists, prompt: "Which features should be marked as shipped?"
- If wiki repo exists, update Home page version + Release History page
- Update auto-memory with new version and shipped features

### Phase 4: Consistency Audit (automated, user reviews)

Cross-check ALL discovered docs for:
- Stale version references (any mention of old versions)
- Feature list mismatches across docs
- Status words that contradict the release ("planned" for shipped features, "alpha" after stable)
- Broken internal links

Present findings. Fix automatically or ask for guidance.

**Gate:** User reviews audit results before committing.

### Phase 5: Commit & Release (user confirms)

- Stage all changes, show diff summary
- Commit: `docs: release vX.Y.Z — <theme>`
- Push main
- If wiki repo: commit and push separately
- **Gate:** User confirms release notes before `gh release create`
- Create GitHub release, set as latest
- Verify release is published

### Phase 6: Post-release Verification

- `gh release view` confirms published and latest
- Quick re-scan for any stale version refs that slipped through

### Error Handling

| Condition | Action |
|-----------|--------|
| Dirty git status | Stop, tell user to commit or stash |
| Version source not found | Ask user, save to memory |
| Wiki repo not found | Skip wiki steps, note in output |
| `gh` not authenticated | Stop, provide auth instructions |
| Push fails | Stop, don't create release |

### Scope Boundaries

The skill does NOT:
- Build or test code (use verification-before-completion)
- Run security audits (separate workflow)
- Run code simplification (use code-simplifier)
- Create PRs (pushes directly — release commits are doc-only)
