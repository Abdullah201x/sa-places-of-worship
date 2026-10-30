# Manara Redesign: Utility-First Architecture

- **Status:** proposal. Nothing in this document is built yet. Decisions D1–D6 recorded 2026-10-30 (§6).
- **Date:** 2026-10-30
- **Inputs:** `design prompt.md`, `HANDOFF.md`, `OSM_IDEAS.md`, `NEXT_LEVEL_ROADMAP.md`, and the current code (`frontend/`, `backend/`, `pipeline/`).

## 0. Ground rules this design keeps

The design prompt is written for a generic community portal. Manara is a more specific product, so these constraints win over the prompt where they conflict:

| Constraint | Effect on the design |
|---|---|
| **OSM compliance** (memory + `HANDOFF.md` §2): the full dataset comes only from Geofabrik's public extract + daily diffs; no bulk reads from `api.openstreetmap.org`; per-object reads only from the user's browser, on user action; no `tile.openstreetmap.org`. **D3 adds one source:** OSM's own minutely replication diffs (`planet.openstreetmap.org/replication/minute`), for the change feed only. | The change feed is **near-live** (a few minutes behind), read from replication files, never from the editing API (§3.3). Freshness is shown like Osmose's "20h" age label (§3.3.4). Osmose and Overpass are **on-click browser calls** (D4). Nothing runs as a server-side crawl. |
| **VPS:** 2 vCPU, 3.8 GiB RAM, about 2.2 GiB free, shared with Rahma. Pipeline ≤ 1.5 GiB, API 256 MiB, DB 512 MiB. | No SSR Node server (Next.js or SvelteKit). The frontend stays **static files served by Caddy**. Anything heavy (Planetiler) runs in GitHub Actions, not on the VPS. |
| **Self-hosted, strict CSP** (`default-src 'self'`, no CDN, `font-src 'self'`). | Every new library is bundled. Each new external host needs an explicit CSP line, listed in this doc. |
| **No "fix all" edits.** At most 50 objects per changeset, about 10 changesets per hour, and changesets are always closed. | Task and QA flows keep a human reviewing each edit. Batching stays as it is in `editing.js`. |
| **Scope (D1): places of worship only.** | Content, rules and pages cover places of worship only. The engines (tasks, QA rules, change feed, tag directory) keep a `theme` field, which costs nothing, but no other theme is planned. |

---

## 1. Functional Audit & Problem Matrix

### 1.1 Personas mapped to what Manara offers today

| Persona | Primary jobs | What exists | Gap |
|---|---|---|---|
| **New / casual mapper** | Understand what to fix. Make a first safe edit. Learn the Saudi conventions (`name`, `name:ar`, `name:en`, denomination). | About page. Guest notice in the details panel. Login modal (with a confusing "advanced: client ID" section). Add-mosque modal with presets. | No onboarding path or "start here" task. Conventions are scattered across the issue labels. Nothing connects "this is wrong" to "here is the rule and why". |
| **Active mapper / validator** | Work a queue fast. Avoid duplicating others' work. See what changed since yesterday. Catch vandalism. | Improve mode with 12 issue types. N/P/F/S shortcuts. Shared review marks. Batch upload. My-edits history. Verified-edits feed. Exports to MapRoulette, JOSM and Overpass. | No claiming or locking, so two mappers can work the same area. No feed of *non-Manara* edits to mosques (deletions, tag regressions). The queue only lives on the map, with no dense list view. Shortcuts break on an Arabic keyboard layout. |
| **Coordinator** (admins only, D6) | Run a sprint in one city or district. Track progress. Assign validation. | Nothing. `/community` shows province totals and history. | No sprint or campaign object, no progress per area, no validation step. |
| **Data consumer / developer** | Download clean data per region. Query by bbox. Read the data model and licence. | `/data/*.geojson` (whole country, undocumented). `/api/v1/*` with Swagger at `/api/docs` (not linked from the UI). "Export current list" (CSV, GeoJSON). | No downloads page, no per-region files, no field dictionary, no stated licence or attribution on the files, no changelog. |

### 1.2 Friction points in the current UI (from the code)

| # | Friction | Evidence | Remediation |
|---|---|---|---|
| F1 | **One sidebar does everything**: mode switch, stats, basemap, 4 toggles, search, religion filter, 12 issue rows, size and Qibla thresholds, date filter, exports, radius slider **and** the details panel. Mode-specific blocks are switched with `style="display:none"`. | `frontend/index.html` lines 17–240 | Split into a **shell** (nav, command bar, status bar) plus **per-workspace panels** (filters on the start side, inspector on the end side). See §2.3. |
| F2 | **No real routes.** Everything is `index.html` plus URL params. `/community`, `/about` and the FastAPI SEO pages each have their own look. | `frontend/vite.config.js`, `backend/app/templates/` | One route map (§2.1) with a shared shell. SEO pages link into workspaces with filters prefilled. |
| F3 | **Heavy first load.** The map waits for places (7.4 MB raw, 257 KB brotli) and gaps (425 KB brotli). The bottleneck on mobile is parsing them, not downloading. Suggestions (938 KB brotli) load only when toggled on. | `summary.json`, `HANDOFF.md` §5, measured 2026-10-30 | App shell first. Overlays as **PMTiles** (§2.5, Phase 5). The suggestions bundle stays static (decided 2026-10-30; see Phase 0). |
| F4 | **Shortcuts tied to the key character.** `e.key` returns `ى` for the N key on an Arabic layout, so N/P/F/S/J/I/O/? all stop working. | `frontend/src/review.js:361` | Match on `e.code` (`KeyN`, `Slash`) so shortcuts follow the physical key whatever the layout (§3.4). |
| F5 | **Physical CSS properties.** 34 `left`/`right` declarations against 4 logical ones, so RTL relies on overrides. | `frontend/src/styles/index.css` | Logical properties everywhere (`inset-inline-start`, `margin-inline-end`, `text-align: start`). |
| F6 | **Decoration over information.** Glassmorphism (`backdrop-filter`), `logo-glow`, gradients, emoji icons as the only issue marker, and colour-only status. | `index.css` `:root`, `index.html` `.improve-item-icon` | Flat panels, 1 px borders, real icons with a text label, and status that is *shape + text + colour* (§2.4). |
| F7 | **Inline styles in markup** (colours, spacing) bypass the theme and break dark/light switching. | e.g. `#details-guest-tools-notice`, `#btn-submit-add-mosque` | Tokens only. Lint rule: no `style=` attributes in templates. |
| F8 | **No coordination primitive.** Review marks hide *fixed* issues, but nothing reserves *work in progress*. | `backend/app/schema.py` (`review_marks`) | Task locks with a TTL (§3.1). |
| F9 | **Blind to outside edits.** The verified-edits feed only shows Manara's own changesets. A mosque deleted or renamed elsewhere goes unnoticed. | `community_data.py /edits/recent` | Daily **change detection** between consecutive datasets (§3.3). |
| F10 | **Dead ends for developers.** `/api/docs` exists but isn't linked. `/data/*` files have no README, licence or schema. | `frontend/index.html`, `deploy/Caddyfile.container` | `/data` hub page with a file manifest, field dictionary, ODbL notice and API examples (§2.1). |
| F11 | **`app.js` is 3,464 lines** with global mutable state shared across modes. Every new feature risks breaking another mode. Recent fixes (`fc1c808`, `7679a5e`) patched symptoms of this. | `frontend/src/app.js` | Split into iD-style *modes* (browse, select, add, review) with `enter`/`exit`, plus a store (§5, Phase 1). |

### 1.3 Remediation strategy in one line per persona

- **New mapper:** `/start` gives a 3-step path: sign in, then one guided fix from a curated "easy" queue (for example `missing name:en` with the transliteration suggestion), then the matching tag rule. Every issue links to its rule in `/tags`.
- **Mapper/validator:** `/qa` is a list-first queue with the map beside it. `/changes` is the near-live change feed (minutes behind OSM). Both are fully keyboard-driven.
- **Coordinator (an admin):** `/tasks` holds sprints over a region or polygon. Work is split into tiles with lock → map → validate states.
- **Data consumer:** `/data` holds per-region downloads, a field dictionary, the API, and Overpass presets that run in the browser on click.

---

## 2. Modular Architecture & Sitemap

### 2.1 Route map

The default language is Arabic at the root. English content pages live under `/en/` so `hreflang` works (the FastAPI SEO pages already emit it). The map workspaces keep language in local settings and the `lang` param, as today.

```
/                              Workspace home: resumes the last workspace, else /map
├── /map                       Explore: density, gaps, suggestions (today's modes 1 and 2)
│     ?layer=places,gaps,sugg&view=z/lat/lon&sel=way/123
├── /qa                        QA queue, list + map (today's mode 3, rebuilt)
│   └── /qa/:ruleId            One rule's queue, e.g. /qa/missing_name_en
├── /changes                   Daily change feed (new)
│   └── /changes/:datasetVer   One day's diff
├── /tasks                     Sprints list (new)
│   ├── /tasks/new             Sprint form (admins only)
│   └── /tasks/:slug           Sprint board: tile grid + map + stats
│       └── /tasks/:slug/:tile Focused tile view (lock, map, validate)
├── /tags                      Saudi tagging directory (new, static)
│   └── /tags/:key  /tags/:key=:value
├── /start                     Onboarding path (new, static + 1 live queue)
├── /guides/:slug              Guides: names, denominations, outlines vs nodes, JOSM setup
├── /data                      Downloads, field dictionary, licence (new, static + manifest)
│   └── /data/api              API reference (links /api/docs) + copy-paste examples
├── /community                 Exists: stats, history, opt-in leaderboard, verified edits
├── /region/:code              Exists (SSR SEO): becomes the region hub linking to
│                              /qa, /changes, /tasks filtered to that region
├── /place/:type/:id           Exists (SSR SEO): adds "open in /map", "issues", "history"
├── /me                        Profile, my marks, my edits, my locks, settings, delete account
├── /about  /privacy           Exist
└── /en/...                    English mirror of the static content pages (tags, guides, start, data)
```

**No dead ends.** Every page has at least one *action* link into a workspace with filters prefilled. Every workspace item links to its documentation (rule → tag page) and its external tools (iD, JOSM, osm.org history, OSMCha by area).

### 2.2 Navigation model

- **Top bar (40 px):** product mark · workspace tabs `Map | QA | Changes | Tasks` · command palette field · reference menu `Tags | Guides | Data` · dataset badge · language · user.
- **Command palette** (`Ctrl+K` or `/`): searches places (existing `/api/v1/search`), regions, rules, tag pages and commands ("toggle gaps layer", "go to Riyadh"). This is the single entry from *discovery* to *execution*.
- **Breadcrumbs** inside workspaces only, for example `QA › Missing English name › Riyadh (SA-01)`. Each segment is a filter you can remove.
- **Freshness indicators (top bar, Osmose-style):** two compact age labels, for example `مباشر 2د · بيانات 20س` / `Live 2m · Data 20h`. They are specified in §3.3.4.
- **Status bar (24 px):** items in view · selection · pending batch count · `?` shortcut hint.

### 2.3 Layout wireframes

#### 2.3.1 Desktop workspace shell, Arabic (RTL)

The start side is on the right. **The map is never mirrored**: north is up and east is right in both languages.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ [م] منارة │ الخريطة  الجودة  التغييرات  المهام │ [⌘K ابحث أو نفّذ أمراً…] │ مباشر 2د · بيانات 20س │ EN │ 👤 │  ← top bar
├─────────────────────┬────────────────────────────────────────┬───────────────────┤
│ INSPECTOR (end)     │                                        │ FILTERS (start)   │
│ 320px, collapsible  │                MAP                     │ 280px, collapsible│
│                     │   (MapLibre / Leaflet, not mirrored)   │                   │
│ مسجد الملك فهد      │                                        │ القاعدة ▾         │
│ way/123456 · v7     │   ┌──────────┐                         │ ☑ اسم إنجليزي     │
│ ─────────────────   │   │ layers ▤ │ ← map controls stay     │ ☐ بدون مذهب       │
│ ⚠ name:en مفقود     │   └──────────┘   in the corners         │ المنطقة ▾ SA-01   │
│  [اقتراح: King Fahd │                  (top-end corner)      │ ─────────────     │
│   Mosque] [تطبيق E] │                                        │ القائمة (412)     │
│ ─────────────────   │                                        │ ▸ مسجد النور  1.2كم│
│ tags (LTR table)    │                                        │ ▸ جامع الراجحي 1.9 │
│  amenity  = place…  │                                        │ ▸ …   (virtual)   │
│  religion = muslim  │                                        │                   │
│ [iD I] [JOSM J] [F][S]                                       │                   │
├─────────────────────┴────────────────────────────────────────┴───────────────────┤
│ بيانات 2026-10-30 02:41 · 412 في العرض · المحدد: way/123456 · دفعة: 3 · ? اختصارات │  ← status 24px
└──────────────────────────────────────────────────────────────────────────────────┘
```

In English (LTR) the two side panels swap: filters on the left, inspector on the right. The map, its controls and the tag table don't move.

#### 2.3.2 QA queue in list-first mode (toggle `L`)

When you want the list rather than the map:

```
┌ QA › Missing English name › SA-01 ─────────────────────────── [Map ◧] [List ▤] ┐
│ ┌──────┬──────────────────────┬───────────┬────────┬───────┬─────────┬────────┐ │
│ │ sev  │ name (dir=auto)      │ object    │ region │ dist  │ age     │ status │ │
│ ├──────┼──────────────────────┼───────────┼────────┼───────┼─────────┼────────┤ │
│ │ ▲ hi │ جامع الملك فهد        │ way/12345 │ SA-01  │ 1.2km │ 3y      │ ○ open │ │ ← j/k move
│ │ ● md │ مسجد النور            │ node/987  │ SA-01  │ 1.9km │ 11d     │ ◐ lock │ │   Enter = inspect
│ │ ● md │ مسجد الرحمة           │ way/5521  │ SA-01  │ 2.4km │ 2y      │ ✓ fixed│ │   F/S = mark
│ └──────┴──────────────────────┴───────────┴────────┴───────┴─────────┴────────┘ │
│ 412 rows · sort: distance ▾ · columns ▾ · export ▾ (CSV · MapRoulette · JOSM)   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

#### 2.3.3 Mobile (< 768 px)

```
┌────────────────────────────┐
│ [≡] منارة  [🔍]  ● 2د · 20س │
├────────────────────────────┤
│                            │
│           MAP              │
│                            │
├────────────────────────────┤ ← bottom sheet, 3 snap points:
│ ━━━  مسجد النور · node/987  │   peek 64px / half / full
│ ⚠ بدون مذهب   [iD] [✓] [⏭] │
├──────┬──────┬──────┬───────┤
│ خريطة │ جودة │ تغيير │ مهام  │ ← bottom tabs (thumb reach)
└──────┴──────┴──────┴───────┘
```

### 2.4 Visual system (utility, not decoration)

- **Surfaces:** two neutral surface levels, 1 px borders, no blur, no glow, no gradients. Same tokens in dark and light, with `prefers-color-scheme` as the default.
- **Type:** Cairo Variable (already self-hosted) for Arabic and Latin UI. The system mono stack (`ui-monospace, …`) for tags, IDs and coordinates, which costs no extra bytes. Drop Outfit and Plus Jakarta Sans (saves 2 font families). Base size 14 px for Arabic body text (Arabic needs it) and 13 px for dense Latin tables. Line-height 1.45 for Arabic, 1.3 for tables.
- **Density:** 28 px table rows, 32 px controls, 8 px spacing grid. "Comfortable" density is a user setting, not the default.
- **Status badges:** always *glyph + text + colour*: `○ open`, `◐ locked`, `● mapped`, `✓ validated`, `✕ invalid`, `⏭ skipped`. Severity uses `▲ high`, `● medium`, `▽ low`. Never colour alone (also an `OSM_IDEAS.md` §6 item).
- **Icons:** one outline icon set, bundled as SVG sprites, replacing the emoji. Directional icons (back, next, chevrons) mirror in RTL. Icons with a real-world direction (compass, Qibla arrow, map north) never mirror.

### 2.5 Component tree

```
<AppShell>                         static: Astro layout; interactive parts are Svelte islands
├── <TopBar> ─ <WorkspaceTabs> <CommandPalette> <DatasetBadge> <LangToggle> <UserMenu>
├── <Workspace kind="map|qa|changes|tasks">
│   ├── <FilterPanel side="start">       per-workspace filter schema → generic renderer
│   │   └── <VirtualList>                10k+ rows, windowed
│   ├── <MapView>                        single map instance shared across workspaces
│   │   ├── <LayerControl>               places · gaps · suggestions · task tiles · changes
│   │   ├── <SelectionLayer>
│   │   └── <PendingEditsOverlay>        immutable edit overlay (OSM_IDEAS §3)
│   └── <Inspector side="end">
│       ├── <ObjectHeader>  <IssueList>  <QuickFixes preset=…>  <TagTable dir="ltr">
│       └── <ActionBar>  iD · JOSM · osm.org history · OSMCha (area) · mark F/S
├── <StatusBar>
└── <Overlays> ─ <EditDiffDialog> <BatchDock> <ShortcutSheet> <AuthDialog> <Toasts aria-live>
```

A single store (Svelte runes or a plain observable module) holds `dataset`, `filters`, `selection`, `pendingEdits`, `locks` and `session`. Workspaces read from it, and the URL is a serialisation of it (as `Permalink` does today).

### 2.6 Key interaction flows

**Discovery to execution (validator, about 3 keystrokes):**
`Ctrl+K` → type "الرياض" → Enter (map flies to SA-01) → `2` (QA workspace, region filter carried over) → `j`/`k` to pick → `I` opens iD with `comment` and `hashtags` prefilled → back in Manara, `F` marks it fixed → after upload, `POST /api/v1/edits` verifies it (existing).

**New mapper:**
`/start` → "Sign in with OSM" (PKCE, existing) → curated queue `missing_name_en` limited to named mosques with a GASGI transliteration suggestion → the inspector shows the diff `name:en = King Fahd Mosque` → the user edits or accepts → upload one changeset → a success card links to `/tags/name:en` and "next easy fix (N)".

---

## 3. Core Feature Specifications

### 3.1 Local Task Tracker (`/tasks`)

**Purpose:** coordinate sprints ("Add missing mosques in Al-Kharj", "English names in Eastern Province") without rebuilding HOT Tasking Manager. It is deliberately small: tiles, locks, two states of review, and progress computed from Manara's own daily data.

**Definitions**
- **Sprint:** an area (region code or drawn polygon), a theme, a set of rules (issue rule IDs and/or `gap` cells with urgency ≥ N), a date window, a hashtag, and instructions in Arabic and English.
- **Tile:** an aggregation of the existing 0.004° gap grid into 5×5 blocks (0.02°, about 2.2 km). The grid already exists in `calculate_gaps.py`, so tile IDs are stable across days: `tile = (floor(gx/5), floor(gy/5))`.
- **Tile workload:** the count of matching issues plus gap cells inside the tile, recomputed after each pipeline load.

**State machine**
```
           lock(mapper)              done              lock(validator≠mapper)
 ready ───────────────▶ mapping ───────────▶ mapped ─────────────────────────▶ validating
   ▲  ◀── expire (2h) ──┘   │                  ▲                                │   │
   │                        └ release ─▶ ready │◀──────── invalidate(reason) ───┘   │ approve
   │                                           │                                    ▼
   └───────────── reopen (admin) ◀────────── validated ◀──────────────────────────┘
 Side states: skipped(reason: no imagery | not inhabited | out of scope), split (admin)
```

**User actions**
1. *An admin* creates a sprint: picks region/polygon, theme, rules and dates. The preview shows the tile count, the total workload and the estimated tiles with zero work (which are pre-set to `validated:auto-empty`).
2. *Mapper* opens the board, presses `N` (next ready tile, nearest-first or highest-workload-first), then `L` to lock. The map zooms to the tile, the QA list filters to the tile, and an iD/JOSM link opens with the tile bbox, `comment` = sprint title and `hashtags` = `#sa-worship-map;#manara-<slug>`.
3. *Mapper* presses `D` (done): state becomes `mapped`. A note field is optional.
4. *Validator* (≥ `MANARA_MIN_CHANGESETS`, and not the tile's mapper) locks a `mapped` tile. The inspector shows the tile's verified Manara edits (from `edits`) and the residual issue count from the latest dataset. They press `A` (approve) or `X` (invalidate with a required reason).

**Inputs and outputs**
| Input | Source |
|---|---|
| Area polygon | `regions.geom` or user-drawn GeoJSON (validated: inside the SA boundary, ≤ 5,000 km², ≤ 2,000 tiles) |
| Workload | `places` + `gaps` + rule evaluation in PostGIS, run in `load_db.py` after each load |
| Edits per tile | `edits.objects` (verified changesets), spatially joined |

| Output | Consumer |
|---|---|
| Board JSON (tiles as a compact array, not GeoJSON) | `/tasks/:slug` |
| Sprint progress history | `/community` and the region pages |
| MapRoulette challenge GeoJSON per sprint | exporter (extends `exporters.js`) |

**Edge cases**
- **Data lag:** a tile mapped today still shows its issues until tonight's pipeline run. The UI labels residual issues as "pending data refresh (next run 02:30 Riyadh)" when the tile has verified edits newer than `dataset_versions.published_at`, so validators don't invalidate correct work.
- **Lock expiry:** 2 h TTL, renewed by activity (any `PUT` on the tile). An expired lock returns the tile to its previous stable state, never to `validated`. A user holds at most 3 locks at a time.
- **Concurrency:** each tile row has a `rev` integer. `PUT` must send `If-Match: <rev>`. A stale rev gets 409 and the client refetches. Two tabs of the same user count as the same lock.
- **Self-validation** is rejected at the API level, not just hidden in the UI.
- **Offline (Phase 6 PWA):** you cannot take a lock while offline. If a lock is held when the connection drops, its expiry is shown and queued edits upload normally. The tile state changes only after a successful sync.
- **Empty tiles** start as `validated` with `auto=true`. An admin can reopen them.
- **Overlapping sprints:** allowed. Tile state is per sprint. The board warns when another active sprint covers the same tile.
- **Who creates sprints (D6):** admins only, i.e. the existing `users.is_admin` flag from `MANARA_ADMIN_UIDS`. There is no separate coordinator role. Mappers and validators work on sprints but can't create, edit, reopen or split them.

**Compliance:** the tracker reads only Manara's DB. iD and JOSM links are navigation only. No new OSM API calls.

### 3.2 Saudi Tagging Directory (`/tags`)

**Purpose:** a fast, searchable reference for the conventions Manara's rules enforce, where **one rule ID links issue, fix and documentation**.

**Content model:** YAML files in the repo (`content/tags/*.yaml`), reviewed by PR, so governance is the GitHub review. They are compiled at build time into static pages plus a search index.

- **Seeded from `@openstreetmap/id-tagging-schema`**, which is already a devDependency through `id-schema-plugin.js`: labels, field types, options and deprecations.
- **Saudi overlay** added on top:
  - Saudi-specific notes;
  - good and bad examples;
  - the related Manara rule IDs;
  - name conventions;
  - links to the OSM wiki pages.

**Entry schema (summary; full type in §4)**
```yaml
key: name:en
status: approved            # approved | de facto | in use | deprecated | discouraged
applies_to: [node, way, relation]
label: { ar: الاسم بالإنجليزية, en: English name }
saudi_notes:
  ar: يُكتب نقلاً صوتياً وفق … ولا يُترك مطابقاً للاسم العربي
  en: Transliterate per …; never copy the Arabic script into name:en
examples:
  good: [{ tags: { name: جامع الملك فهد, name:en: King Fahd Mosque } }]
  bad:  [{ tags: { name: جامع الملك فهد, name:en: جامع الملك فهد }, why: { en: same as name } }]
rules: [missing_name_en]     # issue rule IDs in frontend/src/validator.js (RULE_IDS)
tools: [transliterate]       # embeds the /api/v1/transliterate box
wiki: https://wiki.openstreetmap.org/wiki/Key:name:en
```

**Live usage stats ("local taginfo"):** the pipeline counts key and value usage inside the SA boundary from the extract it already streams with osmium, for example how many `amenity=place_of_worship` have `name:en`, `denomination` and so on. It writes `tag_stats_sa.json` (small, ≤ 200 KB) and a snapshot table for trends. Cost: one more pass in the existing osmium handler. It counts, it doesn't hold geometry, so memory stays flat.

**User actions:** `/` focuses search. The search uses the existing `arabic.js` normalisation, so أ/ا, ة/ه, ى/ي and جامع/مسجد all match. Results show key=value, label, status badge, SA usage count and a "%" bar. Enter opens the entry. On an entry, `Q` opens the matching QA queue and `O` runs "Overpass: find these in this region" in the browser (§3.3.5).

**Initial content (worship theme first):**
- `amenity=place_of_worship`, `religion`, `denomination`, `building=mosque`, `place_of_worship=*` (if Saudi practice for jamea/musalla is agreed by the community);
- `name`, `name:ar`, `name:en` and the transliteration guide;
- `wheelchair`, `female=*`-style women's-area tagging (agree the convention first; see `NEXT_LEVEL_ROADMAP.md` §2.1);
- a "deprecated → replacement" table that matches the `outdated_tags` rule.

Out of scope (D1): roads, addresses and natural features. The directory covers places of worship and the name tags they use.

**Edge cases**
- **Disputed conventions:** an entry can have `status: discussion` with links to the community thread. Rules tied to it are marked *advisory* and never block an upload.
- **Language fallback:** a missing English text shows the Arabic with a `lang="ar"` badge. Never show an empty field.
- **Mixed-direction values:** tag keys and values are always rendered in `<code dir="ltr">`. Arabic values inside them use `<bdi>`, so `name=جامع الملك فهد` doesn't scramble.
- **Schema drift:** a CI check fails if a YAML entry references a rule ID that no longer exists, or if a rule has no tag page.

**Compliance:** fully static. Usage stats come from the Geofabrik extract. Overpass runs only when the user clicks "Run", from their own browser, one request at a time, within one region's bbox (§3.3.5).

### 3.3 Live QA & Change Monitor (`/changes`)

**Purpose:** see changes to places of worship in Saudi Arabia **within minutes**, flag the risky ones, and always show how fresh each source is.

#### 3.3.1 Two sources, one feed

| Source | Delay | What it catches | Role |
|---|---|---|---|
| **Live:** OSM minutely replication diffs (`planet.openstreetmap.org/replication/minute`) | about 2–5 min | Tag edits and deletions of known places. New tagged nodes. New tagged ways and relations (their location may be pending until the daily run). | Fast alerts |
| **Daily:** diff of consecutive Manara datasets (Geofabrik extract) | about 24 h | Everything, including geometry changes, node→outline upgrades, the pipeline's POI merge, and issues that were fixed | Reconciliation and ground truth |

Both write to `change_events` with a `source` field. The daily run then reconciles the two:
- a live event that the daily diff confirms gets `confirmed = true`;
- a change the live stream missed (for example while the replicator was down) is added with `source = 'daily'`;
- a live event whose object ends the day unchanged (it was reverted within the day) is marked `reverted_same_day`.

The map, QA lists and stats **still use the daily dataset**. Live events never patch the dataset, so there is only one version of the truth. Instead, the inspector shows a banner when a place has live events newer than the dataset: "changed 12m ago in OSM. Data shown here is 20h old." The banner links to the event.

#### 3.3.2 Live replicator (`manara-live`, a new Coolify resource)

- **Container:** `python:3.12-slim` + `pyosmium`. Cap of **192 MiB and 0.25 CPU**. It is separate from the pipeline so that a crash in one doesn't stop the other. At the pipeline's nightly peak the two together use about 1.2 GiB, which is inside the 2.2 GiB free.
- **Loop:**
  1. Every 60 s, read `replication/minute/state.txt` (one small request). If `sequenceNumber` is ahead of the last processed sequence, download the missing `.osc.gz` files **one at a time, in order**.
  2. If more than 3 h behind (after an outage), catch up with **hourly** diffs instead (`replication/hour`, about 4.4 MB each, measured), then resume minutely.
  3. If more than 48 h behind, stop catching up. Jump to the current sequence, record the gap, and let the daily run cover it.
  4. Stream-parse each file with pyosmium from a temp file, which is deleted after processing. Nothing accumulates on disk.
- **Filtering** (a minute diff measured about 45 KB gzipped and about 290 ways worldwide, so this is cheap):
  - **Known-places cache:** `(type, id) → {version, centroid, key tags}` for about 14k places, loaded from `places` + `live_places`, so it is tiny.
  - **Node** in the cache: a `modify` or `delete` event. **Node not in the cache** with worship tags, inside the SA bbox and then inside the prepared boundary polygon: a `created` event.
  - **Way or relation** in the cache: an event using the cached centroid. **Not in the cache** but with worship tags: try to place it from nodes in the same diff. If that works and it is inside SA, emit `created`. If not, park it in `live_pending` (bounded, expires after 48 h). The daily run, which has full geometry, then confirms or drops it.
  - **Deletions carry no tags in the diffs** (verified; only id, version and node coordinates). Only cached objects can be recognised, which is enough: a deleted object Manara didn't track isn't a place of worship we know about.
  - The worship-tag test is **one shared predicate** (`pipeline/worship_tags.py`), used by `extract_places.py`, the replicator and the daily diff, so they can't disagree.
- **Flags:** the same rule set as the daily diff (§3.3.6), in a shared `change_rules.py`.
- **Writes:** one transaction per diff: the events plus `replication_state(sequence, osm_timestamp, processed_at)`. Events are idempotent on `(osm_type, osm_id, version)`.
- **Metadata and privacy:** the diffs carry `user`, `uid` and `changeset` (verified). Manara **keeps only `changeset`**, which allows a direct OSMCha link, the most useful QA action. `user` and `uid` are dropped while parsing and never stored or logged. The editor's name is still shown only in the browser, on click (the existing `fetchLastEdit` pattern), or on OSMCha and osm.org through the link. This keeps the GDPR-clean stance from Phase 2. Update `privacy.html` to say "we store the changeset IDs of edits to places of worship".
- **Politeness:**
  - User-Agent `Manara/1.0 (+https://manara.saudiosm.org)`;
  - start from `planet.openstreetmap.org/replication/...` and **follow its redirect**. It currently sends replication requests to OSMF's S3 mirror (verified), so OSMF chooses the backend. The base URL is the env var `MANARA_REPLICATION_URL`;
  - at most one state check per minute, no parallel downloads, and back off on 429 and 503;
  - volume: about 45 KB per minute measured, roughly 65–200 MB per day depending on global edit activity.

#### 3.3.3 Feed UI

- **Dense table columns:**
  - age (`<TimeAgo>`, e.g. `4m`);
  - severity;
  - event;
  - name (`dir=auto`);
  - object;
  - region;
  - key diff (`name: A → B` as LTR code);
  - source (`● live`, `◆ daily`, `✓ confirmed`);
  - triage status.
- **Filters:** time window, region, flag, event type, source, and "unreviewed only".
- **Keys:**
  - `j`/`k` move, `Enter` inspects;
  - `A` acknowledges ("this is fine"), `R` flags it as needing a revert;
  - `H` opens osm.org history;
  - `C` opens **OSMCha for the exact changeset** (`osmcha.org/changesets/{id}`) when known, otherwise OSMCha filtered by area and date;
  - `M` opens Osmose issues nearby (§3.3.5).
- **Auto-refresh:** while the tab is visible, the feed polls Manara's own `GET /api/v1/changes?since_id=` every 60 s, using `ETag`. New rows **do not shift the list under the cursor**. Instead a bar appears ("12 new · press `.` to show"), so keyboard users never lose their place.

#### 3.3.4 Freshness indicator (Osmose-style "20h")

Osmose shows how old its analysis is as a compact relative time (`<span class="v-time-ago__text">20h</span>`). Manara shows **two** such labels in the top bar, because it has two sources:

| Label | Measures | Normal / warning / stale |
|---|---|---|
| **مباشر · Live** | Age of the **OSM timestamp** of the last processed replication diff (`replication_state.osm_timestamp`), i.e. how far behind OSM the feed is | `● < 15m` / `▲ < 2h` / `✕ ≥ 2h or replicator down` |
| **بيانات · Data** | Age of the OSM data the map and QA lists show (`dataset_versions` → `pbf_date`) | `● < 36h` / `▲ < 72h` / `✕ ≥ 72h` (matches `MANARA_MAX_DATASET_AGE_HOURS`) |

- **Age of the data, not of processing:** like Osmose, both labels measure the age of the *OSM data*, not when Manara last ran.
- **Format:** `now`, then `Nm`, `Nh`, `Nd`. In Arabic: `الآن`, `N د`, `N س`, `N ي`. Western digits in both languages (§3.5).
- **Markup:** `<time datetime="2026-10-30T02:41:00Z" title="2026-10-30 05:41 الرياض · 02:41 UTC">20h</time>` gives semantic HTML and the absolute time in both time zones on hover. The state uses glyph + colour, never colour alone. It has an `aria-label` such as "Live data, 2 minutes old", and is **not** an `aria-live` region, which would announce every minute.
- **Updates:**
  - the text ticks client-side every 30 s from the stored timestamps, with no refetch;
  - the timestamps are refreshed from `GET /api/v1/freshness` every 60 s (`ETag`) and when the tab regains focus.
- **Click:** opens a popover with both sources, the last sequence number, the last and next pipeline runs (02:30 Riyadh), any recorded replication gap, and a link to `/data`.
- **Reuse:** the same `<TimeAgo>` component is used for event ages in the feed, "last edited" in the inspector, and lock expiry on tiles.
- **Monitoring:** a new `GET|HEAD /api/healthz/live` returns 503 when the live lag is over 2 h. Add it to UptimeRobot as a fourth monitor.

#### 3.3.5 Osmose and Overpass, called on click (D4)

Both APIs send `Access-Control-Allow-Origin: *` (verified), so they work as direct browser calls once they are added to the CSP. Nothing is called on page load, on map pan, or from the server.

- **Osmose:**
  - The inspector button "Osmose issues nearby" (`M`) calls `GET https://osmose.openstreetmap.fr/api/0.3/issues?bbox=<about 500 m around the object>&limit=50`.
  - Results are listed by item, each linking to the Osmose map at that spot.
  - At most one request in flight. Results are cached in `sessionStorage` for 10 minutes.
  - An optional filter shows only worship-relevant Osmose items. Choose the list after reviewing Osmose's item catalogue for Saudi Arabia.
- **Overpass:**
  - Presets on `/data` and on tag pages get a "Run" button that `POST`s to `https://overpass-api.de/api/interpreter` from the browser.
  - Every query is built with `[out:json][timeout:25][maxsize:…]` and a bbox no larger than one region.
  - Results are drawn on the map and can be downloaded as GeoJSON. The OSM JSON → GeoJSON converter is bundled.
  - One request at a time per tab, and the button is disabled while running. A 429 or 504 shows the server's message plainly, with an "open in Overpass Turbo" fallback.
  - The main Overpass instance asks users to stay under about 10,000 queries and 1 GB per day. One person clicking is far below that.
- **CSP change:** `connect-src` gains `https://osmose.openstreetmap.fr https://overpass-api.de` in `deploy/Caddyfile.container`.

#### 3.3.6 Flags (shared by the live and daily sources)

| Flag | Severity | Logic |
|---|---|---|
| `deleted-named-mosque` | high | Named place gone and not matched as `upgraded`. In live mode it is re-checked by the daily run, because a node deleted while an outline is drawn shows up the same way. |
| `name-removed` | high | `name` was present, now missing |
| `religion-changed` | high | `religion` value changed |
| `amenity-removed` | high | `amenity=place_of_worship` removed |
| `new-duplicate` | medium | New place within 50 m of an existing one with a similar name (trigram ≥ 0.6) |
| `name-ar-mismatch` | medium | `name` and `name:ar` both set and different after normalisation |
| `left-boundary` | medium | A known place moved outside the SA polygon |
| `building-downgraded` | low | `building=mosque` → `yes` |
| `issue-fixed` | info | A QA issue present yesterday is gone today (daily only; credited to verified edits where they match) |

#### 3.3.7 Edge cases

- **Replicator down:** the Live label goes red. When it comes back, it catches up hourly, or gives up after 48 h. The daily run fills in any missed events as `source = 'daily'`.
- **Sequence goes backwards** (server reset or migration): pause, log it, turn the label red, and wait for a manual check.
- **Repeated edits to one object in a day:** one event per version, grouped in the UI by object ("3 edits today").
- **Mass changes:** over 200 events from one changeset, or over 500 in a day, are collapsed into a single "bulk change" group with a region breakdown.
- **Pipeline skipped a day:** the daily diff covers two days, and the header says so.
- **Daily publish blocked** by `validate_data.py`: no daily events are emitted. The live feed continues, and the Data label turns amber or red as it ages.
- **Deleted objects** have no current geometry. The event stores the last known centroid and tags from the cache.
- **Live-created places** are inserted into `live_places` so later edits to them are tracked. They are cleared once the daily dataset includes them.
- **Triage** (`acknowledge`, `needs revert`) is a Manara-side note only. Manara never performs reverts. "Needs revert" links to the OSM revert guidance and the object history.

**Compliance:**
- **Full dataset:** the Geofabrik public extract, daily.
- **Change feed:** OSM's replication files, the channel OSMF publishes for consuming changes, read politely and sequentially with an identifying User-Agent.
- **Editing API:** never read in bulk. Per-object reads happen only in the browser, on click.
- **Osmose and Overpass:** called only in the browser, on click, one request at a time.
- **Personal data:** contributor names and uids are never stored.

### 3.4 Cross-cutting: keyboard model

All handlers match on **`KeyboardEvent.code`** (the physical key), so the same keys work with an Arabic or English layout. The shortcut sheet shows both legends (`N / ى`). Shortcuts are disabled in inputs and while a modal is open, as today.

| Scope | Keys |
|---|---|
| Global | `Ctrl+K` or `/` command palette · `?` shortcut sheet · `1`–`4` workspaces (Map, QA, Changes, Tasks; keeps today's 1–3) · `G` then `T` tags, `G` then `D` data, `G` then `C` community · `Esc` close or clear selection |
| Map | `Shift+1`…`Shift+5` toggle layers (places, gaps, suggestions, tiles, changes) · `B` cycle basemap · `+`/`-` zoom · `Q` Qibla compass |
| Lists | `J`/`K` next/prev (also `N`/`P`, kept for muscle memory) · `Enter` inspect · `X` select for batch · `L` toggle list/map |
| Inspector | `I` iD · `Shift+J` JOSM (plain `J` is now list navigation) · `O` view on osm.org (unchanged) · `H` osm.org history · `C` OSMCha (changeset, or area + date) · `M` Osmose issues nearby (on-click call) · `E` apply suggested quick fix (opens the diff dialog, never uploads silently) · `F` fixed · `S` skip |
| Tasks | `N` next ready tile · `L` lock · `D` done · `A` approve · `X` invalidate · `U` unlock |

**RTL note:** "next" and "previous" are letter keys, not arrows. Where arrows are used (inside list widgets), `ArrowDown`/`ArrowUp` are direction-neutral, and `ArrowLeft`/`ArrowRight` are swapped in RTL to follow the reading order.

### 3.5 Cross-cutting: bidirectional rules

1. **Logical CSS only:** `inline-start`/`inline-end`, `text-align: start`. A Stylelint rule bans `left`/`right`/`margin-left`/… outside the map container.
2. **The map is a physical space:** never mirrored. Map controls are placed by logical corner (`top-end`) for consistency with the panels. Scale bar and attribution stay bottom-right in both directions, as OSM attribution convention expects.
3. **Data islands:** coordinates, OSM IDs, tag keys and values, URLs and changeset comments are wrapped in `dir="ltr"` with `unicode-bidi: isolate`. User-supplied names use `dir="auto"`.
4. **Tables:** column *order* follows the reading direction, so in RTL the first column is at the right. Numeric columns are aligned `end` with `font-variant-numeric: tabular-nums`. The tag table is always LTR, because it is code.
5. **Numbers and dates:**
   - Western digits in both languages (`ar-SA-u-nu-latn`), to match OSM data and avoid mixed digit sets in one row.
   - Dates are Gregorian ISO in data views, with an optional Hijri display (`ar-SA-u-ca-islamic-umalqura`) as a user setting on human-facing pages.
6. **Breadcrumb separators and chevrons** flip with the direction. The Qibla arrow, compass and north arrow never flip.
7. **Truncation:** use `text-overflow: ellipsis` with logical padding. Arabic names never get letter-spacing, because it breaks the joining.

### 3.6 Cross-cutting: performance budget

| Metric | Budget | How |
|---|---|---|
| App shell (HTML + CSS + JS, brotli) | ≤ 150 KB | Astro static, Svelte islands, MapLibre loaded only in workspaces |
| Time to an interactive map on 4G mid-range Android | ≤ 2.5 s | No dataset blocks the first paint. Overlays stream as tiles. |
| Places overlay | ≤ 400 KB of tiles per city view | `places.pmtiles` (tippecanoe, z5–z14, attributes trimmed; full tags fetched per object from `/api/v1/places/{type}/{id}`) |
| Lists of 10k+ rows | 60 fps scroll | Windowed `VirtualList`, data from a Web Worker index |
| Client cache | Hits on repeat visits | Datasets and tiles are addressed by dataset version (`?v=` already exists). `Cache-Control: immutable` per version. IndexedDB holds the QA index for the current version. |

---

## 4. Data Models & API Contracts

Conventions: these extend the existing `/api/v1`, `/auth` and `/data` paths. JSON uses `snake_case` to match the current API. State-changing requests keep the existing CSRF rule (`Origin` + `X-Manara-CSRF: 1`). Lists use cursor pagination.

### 4.1 Shared types

```ts
type OsmType = 'node' | 'way' | 'relation';
type OsmRef = `${OsmType}/${number}`;           // "way/123456"
type RegionCode = `SA-${'01'|'02'|'03'|'04'|'05'|'06'|'07'|'08'|'09'|'10'|'11'|'12'|'14'}`;
type DatasetVersion = string;                    // "v20261030T002841Z" (dataset_versions)
type ISODate = string;
type Localized = { ar: string; en?: string };    // Arabic required, English optional (fallback ar)
type BBox = [minLon: number, minLat: number, maxLon: number, maxLat: number];

interface Page<T> { items: T[]; next_cursor: string | null; dataset_version: DatasetVersion }
interface ApiError { error: string; detail?: string; retry_after_s?: number }  // 4xx/5xx body
```

### 4.2 Users and sessions (extends the existing `users` and `sessions` tables)

```ts
type Role = 'mapper' | 'validator' | 'admin';                  // admins create and manage sprints (D6)

interface Me {                                    // GET /api/v1/me
  osm_uid: number;
  display_name: string;
  avatar_url: string | null;
  osm_changesets: number;
  roles: Role[];                                  // validator = osm_changesets >= MANARA_MIN_CHANGESETS
  leaderboard_opt_in: boolean;
  settings: UserSettings;
  active_locks: TaskLockSummary[];
}

interface UserSettings {                          // PATCH /api/v1/me { settings }
  lang: 'ar' | 'en';
  density: 'compact' | 'comfortable';
  calendar: 'gregory' | 'islamic-umalqura';
  home_region: RegionCode | null;
  editor: 'id' | 'josm';
}
```

### 4.3 Places and issue rules

```ts
interface PlaceProps {                            // tile attributes (trimmed) / full via GET /api/v1/places/{type}/{id}
  osm_type: OsmType; osm_id: number; version: number; edited_at: ISODate;
  name?: string; 'name:ar'?: string; 'name:en'?: string;
  religion?: string; denomination?: string; building?: string;
  region_code: RegionCode | null;
  area_m2?: number; anomaly_score?: number; qibla_dev?: number;
  tags?: Record<string, string>;                  // full only
}

type Severity = 'high' | 'medium' | 'low' | 'info';

interface IssueRule {                             // GET /data/rules.json (static, built from validator.js)
  id: string;                                     // "missing_name_en" (existing ids; never renamed)
  theme: 'worship';                               // later: 'roads' | 'names' | …
  label: Localized; description: Localized;
  severity: Severity;
  fixable_in_app: boolean;                        // has a QuickFix preset
  tag_doc: string;                                // "/tags/name:en"
  overpass?: string;                              // template; {{bbox}} placeholder
  advisory?: boolean;                             // never blocks upload
}

interface Issue {
  rule_id: string;
  ref: OsmRef;
  severity: Severity;
  centroid: [lon: number, lat: number];
  region_code: RegionCode | null;
  suggested_fix?: Record<string, string | null>;  // tag diff; null = remove
  review?: { status: 'fixed' | 'skipped'; by_me: boolean; verified: boolean };
}
```

### 4.4 Tasks

```ts
type TileState = 'ready' | 'mapping' | 'mapped' | 'validating' | 'validated' | 'invalidated' | 'skipped';

interface Sprint {
  id: number; slug: string;
  title: Localized; instructions: Localized;
  theme: 'worship';
  area: { region_code: RegionCode } | { polygon: GeoJSON.Polygon };
  rule_ids: string[];
  gap_min_urgency: number | null;                 // include gap cells with urgency >= N
  hashtag: string;                                // "#manara-kharj-2026-11"
  starts_at: ISODate; ends_at: ISODate | null;
  status: 'draft' | 'active' | 'closed';
  created_by: number;                             // osm_uid
  progress: { total: number; by_state: Record<TileState, number>; workload_remaining: number };
}

interface Tile {
  tile_id: string;                                // "tx:ty" in the 0.02° grid
  bbox: BBox;
  state: TileState;
  rev: number;                                    // optimistic concurrency
  workload: number;                               // issues + gap cells, as of dataset_version
  pending_refresh: boolean;                       // verified edits newer than the dataset
  lock?: { osm_uid: number; display_name: string; kind: 'mapping' | 'validation'; expires_at: ISODate };
  mapped_by?: number; validated_by?: number; auto?: boolean;
}

interface TileEvent {                             // append-only audit (mirrors review_events)
  id: number; sprint_id: number; tile_id: string;
  osm_uid: number; from: TileState; to: TileState;
  reason?: string; note?: string; created_at: ISODate;
}

interface TaskLockSummary { sprint_slug: string; tile_id: string; kind: 'mapping' | 'validation'; expires_at: ISODate }
```

### 4.5 Change feed

```ts
type ChangeKind = 'created' | 'deleted' | 'tags_changed' | 'moved' | 'upgraded' | 'version_only';

interface ChangeEvent {
  id: number;
  source: 'live' | 'daily';
  confirmed: boolean;                             // live event confirmed by the daily diff
  reverted_same_day?: boolean;
  osm_timestamp: ISODate;                         // when the edit happened in OSM
  observed_at: ISODate;                           // when Manara saw it
  changeset_id: number | null;                    // live only (the Geofabrik extract drops it); user/uid never stored
  replication_seq: number | null;                 // live only
  dataset_version: DatasetVersion | null;         // daily only
  prev_dataset_version: DatasetVersion | null;    // daily only
  ref: OsmRef;
  prev_ref?: OsmRef;                              // for 'upgraded' (node → way)
  kind: ChangeKind;
  flags: { rule_id: string; severity: Severity }[];
  centroid: [number, number];
  region_code: RegionCode | null;
  name?: string;
  tag_diff?: Record<string, [before: string | null, after: string | null]>;
  version: [before: number | null, after: number | null];
  triage?: { status: 'acknowledged' | 'needs_revert' | 'ok'; by: number; at: ISODate; note?: string };
}

type FreshnessState = 'ok' | 'warn' | 'stale';

interface Freshness {                             // GET /api/v1/freshness (ETag; drives the top-bar labels)
  live: {
    osm_timestamp: ISODate | null;                // OSM time of the last processed diff
    sequence: number | null;
    processed_at: ISODate | null;
    state: FreshnessState;                        // ok < 15m, warn < 2h, stale otherwise or replicator down
    gap?: { from_seq: number; to_seq: number; at: ISODate };  // latest skipped range, if any
  };
  data: {
    dataset_version: DatasetVersion;
    pbf_date: ISODate;                            // OSM time of the extract behind the map
    published_at: ISODate;
    next_run_at: ISODate;                         // 23:30 UTC daily
    state: FreshnessState;                        // ok < 36h, warn < 72h, stale otherwise
  };
  server_time: ISODate;                           // lets the client correct for clock skew
}
```

`server_time` matters because the labels tick in the browser: a phone with a wrong clock would otherwise show "-3h" or "5d". The client computes `offset = server_time − Date.now()` once per refresh and applies it.

### 4.6 Tag directory and downloads (static)

```ts
interface TagDoc {                                // built from content/tags/*.yaml → /data/tags.json + pages
  key: string; value?: string;                    // value omitted = key page
  status: 'approved' | 'de facto' | 'in use' | 'deprecated' | 'discouraged' | 'discussion';
  applies_to: OsmType[];
  label: Localized; saudi_notes: Localized;
  examples: { good: TagExample[]; bad: (TagExample & { why: Localized })[] };
  replaced_by?: Record<string, string>;
  rules: string[]; tools?: ('transliterate')[];
  id_preset?: string; wiki?: string;
  usage_sa?: { count: number; with_key?: Record<string, number>; as_of: DatasetVersion };
}
interface TagExample { tags: Record<string, string> }

interface DataManifest {                          // GET /data/manifest.json, written by the pipeline
  dataset_version: DatasetVersion;
  pbf_date: ISODate;
  licence: 'ODbL-1.0';
  attribution: '© OpenStreetMap contributors';
  files: {
    id: string;                                   // "places-SA-01-geojson"
    scope: 'SA' | RegionCode;
    layer: 'places' | 'gaps' | 'suggestions' | 'boundary' | 'regions' | 'overlays';
    format: 'geojson' | 'csv' | 'pbf' | 'pmtiles';
    path: string; bytes: number; sha256: string; features?: number;
  }[];
  overpass_presets: { id: string; label: Localized; query: string }[];
}
```

### 4.7 New endpoints

| Method + path | Auth | Rate | Request → Response | Notes |
|---|---|---|---|---|
| `GET /api/v1/issues?rule=&region=&bbox=&cursor=` | none | 120/min | → `Page<Issue>` | Server-side mirror of the client rules, for the list view and the API. Computed at load time and stored in `issues`. |
| `GET /api/v1/sprints?status=` | none | 120/min | → `Sprint[]` | |
| `POST /api/v1/sprints` | admin | 10/h | `Sprint` (draft fields) → `Sprint` | Validates area size and tile count |
| `PATCH /api/v1/sprints/{slug}` | admin | 30/h | partial → `Sprint` | |
| `GET /api/v1/sprints/{slug}/tiles` | none | 120/min | → `{ rev_max, tiles: Tile[] }` | Compact; `ETag` by `rev_max` for cheap polling of **our own** API every 60 s while the board is open |
| `PUT /api/v1/sprints/{slug}/tiles/{tile}` | session | 60/min/user | `If-Match: rev`, `{ action: 'lock'\|'release'\|'done'\|'approve'\|'invalidate'\|'skip', kind?, reason?, note? }` → `Tile` | 409 on stale rev; 403 on self-validate or too many locks |
| `GET /api/v1/changes?since_id=&from=&to=&source=&region=&flag=&kind=&cursor=` | none | 120/min | → `Page<ChangeEvent>` | `since_id` for the 60 s refresh, with `ETag` |
| `GET /api/v1/freshness` | none | 120/min | → `Freshness` | `ETag`; tiny |
| `GET\|HEAD /api/healthz/live` | none | | → 200 / 503 | 503 when live lag > 2 h (UptimeRobot) |
| `PUT /api/v1/changes/{id}/triage` | validator | 60/min/user | `{ status, note? }` → `ChangeEvent` | Annotation only |
| `GET /data/manifest.json` · `/data/tags.json` · `/data/rules.json` · `/data/tag_stats_sa.json` | none | static | | Versioned, `immutable` |
| `GET /data/v/{version}/{layer}.pmtiles` | none | static, range | | Caddy serves HTTP range requests natively |

Existing endpoints are kept unchanged: `/auth/*`, `/api/v1/me`, `reviews`, `edits`, `search`, `places`, `suggestions`, `stats`, `transliterate`, `leaderboard`, `edits/recent`, and the SEO routes.

### 4.8 New tables (PostGIS)

```sql
sprints(id serial pk, slug text unique, title jsonb, instructions jsonb, theme text,
        region_code text null, area geometry(Polygon,4326), rule_ids text[], gap_min_urgency real,
        hashtag text, starts_at timestamptz, ends_at timestamptz, status text, created_by bigint)
sprint_tiles(sprint_id int, tile_id text, bbox geometry(Polygon,4326), state text, rev int,
        workload int, lock_uid bigint null, lock_kind text null, lock_expires_at timestamptz null,
        mapped_by bigint, validated_by bigint, auto bool, primary key (sprint_id, tile_id))
tile_events(id bigserial pk, sprint_id int, tile_id text, osm_uid bigint, from_state text,
        to_state text, reason text, note text, created_at timestamptz)
issues(rule_id text, osm_type text, osm_id bigint, severity text, geom geometry(Point,4326),
        region_code text, suggested_fix jsonb, primary key (rule_id, osm_type, osm_id))  -- swapped atomically with places
change_events(id bigserial pk, source text, confirmed bool, reverted_same_day bool,
        osm_timestamp timestamptz, observed_at timestamptz, changeset_id bigint null, replication_seq bigint null,
        dataset_version text null, prev_dataset_version text null, osm_type text,
        osm_id bigint, prev_ref text, kind text, flags jsonb, geom geometry(Point,4326),
        region_code text, name text, tag_diff jsonb, version_before int, version_after int,
        unique nulls not distinct (osm_type, osm_id, version_after, kind))  -- idempotent replays (PG 15+); kept 180 days
replication_state(id int pk default 1, sequence bigint, osm_timestamp timestamptz, processed_at timestamptz,
        last_gap_from bigint null, last_gap_to bigint null, last_gap_at timestamptz null)  -- one row
live_places(osm_type text, osm_id bigint, version int, geom geometry(Point,4326), tags jsonb,
        seen_at timestamptz, primary key (osm_type, osm_id))           -- created live, cleared by the daily load
live_pending(osm_type text, osm_id bigint, version int, tags jsonb, node_refs bigint[],
        seen_at timestamptz, primary key (osm_type, osm_id))           -- new ways/relations without a location yet; 48 h expiry
change_triage(change_id bigint pk references change_events, status text, osm_uid bigint, note text, at timestamptz)
tag_usage_history(dataset_version text, key text, value text, count int, primary key (dataset_version, key, value))
```

`users` gains `settings jsonb`. Sprint management uses the existing `is_admin`, so no role column is added. Expired locks are cleared lazily: any read that finds `lock_expires_at < now()` treats the tile as unlocked, and a sweep runs in `load_db.py`. No new cron container is needed.

---

## 5. Phase-by-Phase Implementation Plan

Each phase can ship on its own. Every phase follows your workflow: commit locally, ask before each push to `main`, then `curl` the live endpoints. RAM impact and OSM compliance are stated for each phase.

### Stack decision

| Layer | Choice | Why (and what was rejected) |
|---|---|---|
| Pages | **Astro, static output** | Builds on Vite, so the two `vite.config.js` gotchas carry over through Astro's `vite` key. Content collections and i18n routing fit `/tags`, `/guides`, `/data` and `/en/*`. It produces static files, so Caddy serves it as today. *Rejected:* Next.js and SvelteKit SSR, which need a Node server container (RAM) and duplicate what FastAPI already does for SEO. |
| Interactive UI | **Svelte 5 islands** | Small runtime, compiled, easy for one maintainer. Islands keep the content pages near zero JS. *Rejected:* React, which has a bigger runtime and gives no benefit here. |
| Styling | **CSS custom-property tokens + logical properties**, no Tailwind | 3.1k lines of existing CSS migrate token by token. Logical properties give RTL for free. Tailwind v4's logical utilities would also work, but would mean a full rewrite of markup for little gain. Revisit only if a contributor team grows. |
| Map | **MapLibre GL JS 6.x** behind `?map=gl` (built in Phase 5). **Leaflet** is still the default until MapLibre is measured on a phone. | Vector overlays (PMTiles), GPU rendering for 60k gap cells, and data-driven styling. It needs the self-hosted RTL text plugin for Arabic labels, the CSP build (`maplibre-gl-csp` + its worker file), and `worker-src 'self' blob:`. Check whether the plugin version needs `'wasm-unsafe-eval'`. |
| Basemap | Esri and CARTO raster (as today), then an **optional** Shortbread `.pmtiles` for the GCC built by Planetiler in **GitHub Actions** (too heavy for the VPS) | Never OSMF tiles (`OSM_IDEAS.md` §5). |
| Backend | **FastAPI + PostGIS** (existing) | New routers: `issues`, `sprints`, `changes`. Stays inside the 256 MiB cap: tile lists are compact arrays, and lists are paginated. |
| Pipeline | Existing `run.py` + new steps `detect_changes.py` (daily diff + reconciliation), `tag_stats.py`, `build_overlays.py` (tippecanoe), `extract_regions_data.py` | Each runs as a subprocess, sequentially. Peak memory stays around today's 970 MiB. |
| Live replicator | New Coolify resource **`manara-live`**: `python:3.12-slim` + pyosmium, one long-running loop, **192 MiB / 0.25 CPU** cap, on the `coolify` network, writing to `manara-db` | Kept apart from the pipeline so the nightly run and the live loop can fail or restart independently. Shares `worship_tags.py` and `change_rules.py` with the pipeline. |
| Tests | pytest (existing) + **Vitest** (already in `package.json`) for rules, keyboard and bidi helpers + Playwright smoke tests in CI (ar and en, desktop and mobile viewports) | |

### Phase 0: Foundations, with no visible redesign. **Done 2026-10-30** (local commits, not yet pushed)
1. ✅ Shortcuts work with any keyboard layout (`frontend/src/keys.js`): Latin letters are used as typed, anything else falls back to `KeyboardEvent.code`. The shortcut sheet has a note (fixes F4).
2. ✅ `index.css` uses logical properties, and the `[dir="ltr"]` override block is gone. Two direction rules remain on purpose (mirrored review arrows; English left-aligns modal inputs that are centred in Arabic, until the Phase 1 form redesign). The 53 styling inline styles moved to the stylesheet. The 15 `display:none` starting states the JS toggles stay inline until Phase 1 rewrites that JS (F5, F7). Added `--color-warn` and `--color-danger` tokens.
3. ✅ Issue rules moved to `frontend/src/validator.js` (`RULES`, `RULE_IDS`, `evaluateRules`). The **existing snake_case ids are kept**, because filters, permalinks and exports use them. Output was checked identical to the old code on all 14,018 places.
4. ❌ **Dropped:** loading suggestions by bbox. Measured: the bundle is already lazy (938 KB brotli, fetched only when Suggestions is turned on), and the bbox API (3° span, 500 results) would lose the country-wide clusters, the counts and search across all suggestions, and the edit-history exclusion. This keeps the `HANDOFF.md` §8 decision. Load size is solved properly by Phase 5 PMTiles.
5. ✅ **Data** age label (§3.3.4) in the sidebar header (`frontend/src/timeago.js`). The pipeline now also writes the full `pbf_timestamp` to `summary.json`, and the label reads it there, with the clock skew taken from the response's `Date` header. Until the server publishes a `pbf_timestamp`, the label shows the date as before. The **Live** label follows in Phase 2b.
6. **Exit:** lint, Vitest, pytest and build pass. The shortcuts work with an Arabic layout. The page looks identical in ar and en, apart from the new label.
7. *RAM:* none. *Compliance:* no change.

### Phase 1: Shell, routing and the QA workspace (2–3 weeks)
1. Introduce Astro with the current `index.html` map mounted as one page (no rewrite yet). Add the `AppShell`: top bar, command palette, status bar.
2. Split `app.js` into modes (browse, select, add, review) and a store. Port the sidebar sections into `FilterPanel` and `Inspector` islands.
3. Build `/qa` as list-first with `VirtualList`, plus `GET /api/v1/issues` (an `issues` table filled in `load_db.py`).
4. New visual system (§2.4). Remove the glass and glow styles and the Outfit and Plus Jakarta fonts.
5. **Exit:**
   - every existing feature is reachable: run through the README's feature list as a checklist;
   - the Permalink format keeps working, with old URLs redirected;
   - Lighthouse performance is at least as good as today on mobile.
6. *RAM:* `issues` adds about 30k rows, which is negligible. *Compliance:* no change.

### Phase 2a: Daily change feed and on-click integrations (1–2 weeks)
1. Move the worship-tag test into `pipeline/worship_tags.py` and the flags into `change_rules.py`. Both are shared by everything that follows.
2. `pipeline/detect_changes.py` diffs the previous and current published places, with upgrade matching, and writes `change_events` (`source = 'daily'`).
3. `/changes` workspace, triage endpoint, links to osm.org history and OSMCha by area and date.
4. Osmose "issues nearby" (`M`) and the Overpass "Run" button (§3.3.5), plus the CSP `connect-src` addition.
5. Show the "issue fixed" events on `/community` (the positive loop).
6. **Exit:**
   - a replay test on two stored datasets produces the expected events;
   - a shrink-blocked run emits no events;
   - a synthetic bulk day collapses into one group;
   - the network tab shows Osmose and Overpass requests only after a click.
7. *RAM:* under 200 MB at peak inside the pipeline step. *Compliance:* the Geofabrik extract. Osmose and Overpass are called only from the browser, on click.

### Phase 2b: Live replicator and freshness labels (1–2 weeks)
1. `manara-live` Coolify resource (§3.3.2): state polling, sequential minute diffs, hourly catch-up, the 48 h give-up rule, `live_places` and `live_pending`.
2. Daily reconciliation in `detect_changes.py`: confirm live events, add missed ones, mark same-day reverts, clear `live_places`, and resolve `live_pending`.
3. `GET /api/v1/freshness`, the Live and Data labels in the top bar, and `/api/healthz/live`. Add the fourth UptimeRobot monitor (exact click-by-click steps will be provided).
4. Direct OSMCha changeset links (`C`) for live events. Update `privacy.html` (changeset IDs stored; names and uids never).
5. **Test first against recorded diffs:** save a day of real minute diffs locally, replay them in pytest, and check the events. Then run the container for 48 h with writes going to a staging table before enabling the feed.
6. **Exit:**
   - the Live label stays under 15 minutes for 48 h;
   - killing the container for 4 h produces an hourly catch-up with no duplicate events;
   - `docker stats` shows `manara-live` under 192 MiB through a nightly pipeline run;
   - no `user` or `uid` values appear anywhere in the DB or the logs.
7. *RAM:* about 100–150 MiB steady (estimate, to be confirmed in the 48 h trial). *Compliance:* replication files only, one request at a time, User-Agent set, redirect to OSMF's mirror followed, and backoff on 429 and 503.

### Phase 3: Tag directory, guides and `/start` (2 weeks)
1. `content/tags/*.yaml` seeded from id-tagging-schema plus the Saudi overlay (worship and names first). Astro content collections, an `/en/` mirror, and a search index using the `arabic.js` normalisation.
2. `pipeline/tag_stats.py` (one osmium pass) writes `tag_stats_sa.json` and `tag_usage_history`.
3. `/start` onboarding with a curated easy queue. Guides: names and transliteration, outlines vs nodes, JOSM Remote Control setup, the review etiquette.
4. CI check: every rule has a tag page and every tag page's rules exist.
5. *RAM:* osmium count pass, flat memory. *Compliance:* static content. Overpass runs only on click, from the browser (Phase 2a).

### Phase 4: Task tracker (3 weeks)
1. Tables `sprints`, `sprint_tiles`, `tile_events`, with create, edit, reopen and split limited to admins (`is_admin`).
2. Board UI, the lock/done/validate flow, iD and JOSM links with comment and hashtags, and MapRoulette export per sprint.
3. Workload and "pending refresh" recomputed in `load_db.py`.
4. Pilot with one sprint (for example one governorate) before announcing it.
5. **Exit:**
   - concurrency tests: two users locking the same tile get one 200 and one 409;
   - self-validation is rejected;
   - expiry works;
   - the board stays usable at 2,000 tiles.
6. *RAM:* small tables. Polling hits our own API with `ETag` (304 most of the time). *Compliance:* no OSM calls.

### Phase 5: Data hub, vector overlays and MapLibre (3–4 weeks). **Mostly done 2026-10-30** (local commits, not pushed; details in `HANDOFF.md` §20)

**Status:** item 1 is half done (manifest, CSV/GeoJSON exports, `/data` page; per-region exports and `.osm.pbf` cuts remain). Item 2 is done (and `pipeline/pmtiles_writer.py` makes real tiles when tippecanoe is missing). Item 3 is done as an opt-in: the whole map runs on MapLibre with `?map=gl` through a "map kit" (`src/map_kit.js`, `kit_leaflet.js`, `kit_gl.js`), verified against Leaflet by Playwright. Item 4's fallback is inverted: Leaflet stays the default and MapLibre is opt-in, until it is measured on a real phone. **The exit criteria are not yet met** (first-load transfer, 60 fps on Android, both need a device or a rethink of how stats/search/filters get their data; the main app still loads the full GeoJSON and does not read the PMTiles).

**Deviations from the text below:** no text layers on the map (cluster counts are DOM markers, popups are DOM; so no glyph server, no RTL text plugin, no `'wasm-unsafe-eval'`); worker via `maplibregl.setWorkerUrl()` with the Vite `?url` asset, CSP gets `worker-src 'self' blob:` (the `maplibre-gl-csp` package no longer exists in v6); CARTO tile hosts were added to `connect-src` because MapLibre fetches tiles; zoom numbers stay Leaflet's (the facade converts), so permalinks are unchanged.

1. `/data` page from `manifest.json`: whole-country and per-region GeoJSON and CSV for places, gaps and suggestions, each with sha256 and ODbL attribution. Optionally per-region `.osm.pbf` cut with `osmium extract` (streaming, low memory).
2. `build_overlays.py`: tippecanoe → versioned `places.pmtiles`, `gaps.pmtiles` and `suggestions.pmtiles`.
3. Migrate `MapView` to MapLibre:
   - CSP build;
   - self-hosted RTL text plugin;
   - CSP additions (`worker-src 'self' blob:`, and `'wasm-unsafe-eval'` only if the plugin needs it).
4. Keep Leaflet behind a `?map=leaflet` fallback for one release.
5. **Exit:**
   - first-load transfer down by more than 80% against today;
   - 60 fps pan on a mid-range Android;
   - attribution visible on every map view.
6. *RAM:* the tippecanoe pass for 14k points plus 60k cells is small. Disk is a few tens of MB per version, and two versions are retained. *Compliance:* everything is derived from the extract. Redistribution is under ODbL with attribution.

### Phase 6: Field PWA and optional integrations (ongoing)
1. Service worker for the app shell, the current dataset version and visited overlay tiles (own files only). Edits queue in IndexedDB and replay through the conflict-checked `applyEdits()`.
2. StreetComplete-style question queue on mobile (`OSM_IDEAS.md` §8).
3. **Only if approved later:** automated MapRoulette challenge publishing with a user-supplied API key, and opt-in alerts (for example Telegram) for high-severity live events in a mapper's home region.

---

## 6. Decisions

| # | Decision | Answer (2026-10-30) | What it changed |
|---|---|---|---|
| D1 | Scope | **Places of worship only** | §0, §3.2. No roads, addresses or natural-feature content. |
| D2 | Framework | **Astro + Svelte islands** | Stack table (§5). Phase 0 stays framework-free; Astro arrives in Phase 1. |
| D3 | Change feed latency | **Add OSM's minutely replication diffs**, with an Osmose-style age indicator | §3.3 rewritten (live replicator + daily reconciliation), §3.3.4 freshness labels, Phase 2b, new Coolify resource `manara-live`. |
| D4 | Osmose and Overpass | **On-click browser calls** | §3.3.5, CSP `connect-src` addition, Phase 2a. |
| D5 | English URLs | **`/en/` for content pages**, `lang` setting for the workspaces | §2.1. |
| D6 | Who can create sprints | **Admins only** (`MANARA_ADMIN_UIDS`) | §3.1, §4.2, §4.7, Phase 4. No coordinator role or request flow. |

A sprint is a mapping campaign over one area (for example "add the missing mosques in Al-Kharj during November"). Everyone can work on sprints; only admins create and manage them. To let someone else run sprints later, add their OSM user ID to `MANARA_ADMIN_UIDS` in Coolify. Note that this also gives them the other admin powers, such as revoking review marks.

## 7. Verification for every phase

- **Run `npm run smoke` in `frontend/` after any UI change** (61 Playwright tests: every route in ar/en at desktop and phone size, the map on both backends with a parity check, and the OSM no-request rules; `HANDOFF.md` §20.6). Lint, Vitest and `vite build` alone missed four bugs in the live pages.

- `python -m pytest tests/ -q`, then `cd frontend && npm run lint && npm run test && npm run build`.
- Playwright smoke tests in ar and en, desktop and mobile:
  - each route renders;
  - shortcuts work with `code`-based events (simulate an Arabic layout);
  - no horizontal overflow in RTL.
- Network-tab audit on the built site:
  - no `tile.openstreetmap.org`;
  - `api.openstreetmap.org` only on user action (login, per-object read, edits);
  - `osmose.openstreetmap.fr` and `overpass-api.de` only after a click, never on load or pan;
  - no request to an origin missing from the CSP.
- On the VPS: `planet.openstreetmap.org` (and the mirror it redirects to) is contacted **only** by `manara-live`, at most about one state check per minute plus one file per new sequence. Check this in the container logs.
- Test edits against `master.apis.dev.openstreetmap.org` only.
- After each push: `curl` `/healthz`, `/api/healthz`, `/api/healthz/freshness`, `/api/healthz/live` (from Phase 2b) and the new endpoints. Check `docker stats` on the VPS so the containers stay within their caps.
