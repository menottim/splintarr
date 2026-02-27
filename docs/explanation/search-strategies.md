# Search Strategies

Understanding how different search strategies work and when to use each one.

## Overview

Splintarr provides multiple search strategies to address different use cases in media library management. Each strategy operates on different assumptions about what content needs attention and when.

## Strategy Types

### Missing Strategy

**What It Searches For**: Content that is completely absent from your library

**Core Concept**: The "missing" strategy addresses the most fundamental gap in a media library: content that you want but don't have at all. This differs from upgrades (content you have but want better versions of) or recent additions (content that just became available).

**How It Works**:

1. Queries Sonarr/Radarr for all items marked as "monitored" that have no files
2. Applies priority sorting based on:
   - Monitored status (explicitly wanted vs. automatic)
   - Download date/air date (older content is often harder to find)
   - Series/movie popularity (popular content has better availability)
3. Selects top N items based on configured batch size
4. Triggers search in Sonarr/Radarr
5. Records search in history to prevent repeats within cooldown period

**Why This Design**:

Missing content represents the highest-value search target because it provides something you completely lack. Finding missing episodes of a partially-downloaded series improves completeness. Finding missing movies fills gaps in collections.

The prioritization considers that older missing content tends to have reduced availability over time. Searching for 5-year-old episodes before last week's episodes can be more valuable because recent content will likely have more opportunities to be found later.

**Typical Use Pattern**:

- **Frequency**: Daily or on-demand
- **Batch Size**: 10-30 items (aggressive but not overwhelming)
- **Best For**: Maintaining library completeness, filling gaps after adding new content to monitoring

### Cutoff Strategy

**What It Searches For**: Content that exists but doesn't meet quality profile cutoff

**Core Concept**: The "cutoff" strategy addresses quality improvement rather than availability. You have the content, but it's below your desired quality threshold (e.g., 720p when you want 1080p, or HDTV rip when you want WEB-DL).

**How It Works**:

1. Queries for items with existing files below quality cutoff
2. Evaluates based on:
   - How far below cutoff (720p vs 1080p cutoff vs 480p vs 1080p cutoff)
   - Release date (newer releases have better quality sources available)
   - Popularity (popular content has more quality options)
3. Selects candidates for upgrade
4. Triggers search for better releases
5. Sonarr/Radarr automatically replaces if better quality found

**Why This Design**:

Quality upgrades are less urgent than missing content. You can watch what you have; missing content is unwatchable. Therefore, cutoff searches typically run less frequently and can afford to be more patient.

The strategy prioritizes items furthest below cutoff because they represent the largest quality gap. A 480p file when you want 4K is a bigger upgrade opportunity than 1080p when you want 4K.

**Typical Use Pattern**:

- **Frequency**: Weekly or bi-weekly
- **Batch Size**: 20-50 items (less urgent, can be larger batches)
- **Best For**: Gradually improving library quality over time, leveraging improved releases

### Recent Strategy

**What It Searches For**: Newly added or recently aired content

**Core Concept**: The "recent" strategy focuses on time-sensitive content: episodes that just aired, movies that just released. This content has the highest chance of finding new releases because indexers are actively uploading them.

**How It Works**:

1. Queries items added to Sonarr/Radarr or aired in last N days (default: 30)
2. Sorts by:
   - Air date (newest first)
   - Addition date (recently monitored content)
   - Missing vs. upgrade (prioritizes missing)
3. Searches recent items repeatedly during availability window
4. History tracking prevents over-searching the same item

**Why This Design**:

New content follows predictable release patterns. TV episodes typically appear on indexers within hours of airing. Movies appear at BluRay/WEB-DL release. Searching recent content frequently maximizes the chance of catching releases during their peak availability window.

Older content has already been searched (or would have been found by missing/cutoff strategies). Focusing on recency optimizes for the highest-value time window.

**Typical Use Pattern**:

- **Frequency**: Every 4-6 hours
- **Batch Size**: 5-15 items (focused, frequent searches)
- **Best For**: Keeping up with currently airing shows, new movie releases

### Custom Strategy

**What It Searches For**: User-defined criteria

**Core Concept**: The custom strategy provides flexibility for specific use cases that don't fit the standard patterns. It allows filtering by tags, years, quality profiles, and other metadata.

**Configuration Examples**:

```json
{
  "monitored_only": true,
  "min_year": 2020,
  "max_year": 2024,
  "tags": ["favorite", "priority"],
  "quality_profiles": ["HD-1080p"],
  "sort_by": "popularity",
  "sort_order": "desc"
}
```

**Use Cases**:

- **Favorites Only**: Search only tagged favorites
- **Era-Specific**: Focus on specific decades or years
- **Quality Tier**: Target specific quality profiles
- **Genre-Based**: Using tag-based filtering for genres

**Why This Exists**:

Standard strategies cover 90% of use cases, but edge cases exist:
- "Search only my 4K instance for 2020+ movies"
- "Focus on anime-tagged content exclusively"
- "Prioritize documentaries during slow months"

Custom strategy provides escape hatch without complicating standard strategies.

## Strategy Interactions

### Avoiding Duplication

The search history system prevents strategies from conflicting:

- **24-Hour Cooldown**: Once an item is searched by any strategy, all strategies skip it for 24 hours
- **Shared History**: All strategies consult the same history table
- **Idempotent Operations**: Searching the same item multiple times doesn't harm, but wastes indexer API quota

**Example Scenario**:

1. Recent strategy searches "Show S05E10" at 8 AM
2. Missing strategy runs at 2 PM, sees search history, skips it
3. At 8 AM next day, cooldown expires, item eligible again

This prevents one item from consuming multiple API calls across strategies.

### Strategy Complementarity

Different strategies serve different phases of content lifecycle:

**Phase 1 - Addition**: Recent strategy catches new content quickly

**Phase 2 - Gap Filling**: Missing strategy finds content recent strategy missed

**Phase 3 - Quality Improvement**: Cutoff strategy upgrades once availability exists

**Phase 4 - Maintenance**: Periodic missing/cutoff searches catch newly available sources

### Batch Size Considerations

Batch size impacts search effectiveness:

**Too Small** (< 5):
- Underutilizes indexer capacity
- Slow progress through backlog
- Many small API calls

**Too Large** (> 100):
- Overwhelming for indexers
- Higher chance of rate limiting
- Longer execution time risks timeout

**Optimal Range** (10-50):
- Balances progress and indexer health
- Aligns with typical indexer rate limits
- Completes within reasonable timeframe

## Search Cooldown Mechanism

### Why Cooldown Exists

**Problem**: Without cooldown, strategies could search the same item repeatedly:
- Recent strategy searches at 8 AM, 2 PM, 8 PM
- Missing strategy searches at midnight
- Same item searched 4 times in 24 hours

**Indexer Impact**: Most items don't get new uploads every few hours. Repeat searches waste API quota and risk rate limiting.

**Solution**: 24-hour cooldown prevents repeat searches while allowing enough frequency to catch new uploads.

### Cooldown Trade-offs

**Advantages**:
- Respects indexer limits
- Prevents API quota exhaustion
- Distributes searches across full backlog
- Reduces database I/O

**Disadvantages**:
- May miss short-lived releases (rare)
- Can't immediately retry after indexer downtime
- Fixed period may not align with release patterns

**Rationale**: The trade-off favors indexer health and quota preservation. Most content remains available for days/weeks. The rare case of a 12-hour-only release is acceptable loss compared to risk of indexer bans.

## Priority and Sorting

### Why Prioritization Matters

With thousands of items potentially needing searches, prioritization determines which items get searched first when batch size limits apply.

**Example Library**:
- 500 missing episodes
- Batch size: 20
- Only 20 get searched per run

Which 20? Prioritization decides.

### Sorting Factors

**Monitored Status**: Explicitly monitored items rank higher than automatic monitoring

**Recency**: Different meaning per strategy:
- Missing: Older = higher (harder to find)
- Cutoff: Newer = higher (better sources available)
- Recent: Newest = highest (time-sensitive)

**Popularity**: Popular content has better availability, more sources, higher success rate

**Quality Gap**: For cutoff, larger gaps prioritized (480p → 1080p before 720p → 1080p)

### Sorting Philosophy

Sorting optimizes for **search effectiveness**, not fairness. The goal is maximizing found content per API call, not evenly distributing searches.

If a popular recent show has 10 missing episodes and an obscure 5-year-old show has 10 missing episodes, searching the popular show first likely yields more results. The obscure show will get its turn, but after higher-probability targets.

## Configuration Patterns

### Daily Operations

**Goal**: Keep up with current content, maintain library completeness

**Pattern**:
```
Recent Strategy: Every 6 hours, batch size 10
Missing Strategy: Daily at 2 AM, batch size 20
Cutoff Strategy: Weekly on Saturday, batch size 50
```

**Rationale**: Recent strategy catches new releases quickly. Missing strategy fills gaps daily. Cutoff strategy improves quality on relaxed schedule.

### Backlog Clearing

**Goal**: Rapidly fill large missing catalog

**Pattern**:
```
Missing Strategy: Every 4 hours, batch size 50
Recent Strategy: Disabled temporarily
Cutoff Strategy: Disabled temporarily
```

**Rationale**: Focus all search capacity on missing content. Once backlog cleared, re-enable other strategies.

### Quality Focused

**Goal**: Maintain maximum quality, completeness less important

**Pattern**:
```
Cutoff Strategy: Every 6 hours, batch size 30
Recent Strategy: Every 8 hours, batch size 10
Missing Strategy: Weekly, batch size 20
```

**Rationale**: Prioritize quality upgrades over missing content. Useful for libraries where "good enough" doesn't exist.

### Indexer-Limited

**Goal**: Minimize API usage due to strict indexer limits

**Pattern**:
```
Recent Strategy: Daily, batch size 5
Missing Strategy: Weekly, batch size 10
Cutoff Strategy: Monthly, batch size 20
```

**Rationale**: Conservative batch sizes and infrequent runs respect tight API quotas. Progress is slower but sustainable.

## Success Metrics

### How to Measure Strategy Effectiveness

**Search Success Rate**: Percentage of searches that find releases
- Target: 30-50% for missing, 20-40% for cutoff, 40-60% for recent
- Low rate suggests prioritization issues or unrealistic expectations

**Items Found Per Search**: Average releases found per search operation
- Target: 0.5-2.0 (one release per 1-2 searches)
- Higher is better, indicates good prioritization

**Cooldown Hit Rate**: Percentage of potential searches skipped by cooldown
- Target: 10-30%
- Too high suggests strategies overlapping inefficiently
- Too low suggests searches too infrequent

**API Quota Usage**: Percentage of indexer API quota consumed
- Target: 60-80%
- Too low means underutilizing available capacity
- Too high risks rate limiting

### Adjusting Based on Metrics

**Low Success Rate**:
- Reduce batch size (focus on highest-priority items)
- Adjust sort criteria
- Review quality profiles (too strict?)
- Check indexer quality

**High Cooldown Hit Rate**:
- Reduce search frequency
- Adjust strategies to avoid overlap
- Increase cooldown period

**High API Usage**:
- Reduce batch sizes
- Decrease search frequency
- Consolidate strategies

## Conclusion

Search strategies encode different philosophies about what to search and when:

- **Missing**: Completeness-focused, addresses gaps
- **Cutoff**: Quality-focused, improves existing content
- **Recent**: Timeliness-focused, catches new releases
- **Custom**: Flexibility-focused, handles edge cases

Understanding these philosophies helps configure effective automation that aligns with your library goals and indexer constraints.

## See Also

- [Getting Started Tutorial](../tutorials/getting-started.md) - Setting up your first search queue
- [Configuration Reference](../reference/configuration.md) - All search configuration options
- [Troubleshooting](../how-to-guides/troubleshoot.md) - Solving search issues
