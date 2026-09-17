# Design handoff

Source: `wireframes.html` (Claude Design export, 2026-09-17). Open it in a browser to navigate the interactive prototype. `screens/*.html` are the raw markup blocks of each screen, split from the prototype for reference while building templates. They use inline styles and prototype-only tags (`sc-if`, `sc-for`); copy the layout and values, not the markup.

## Tokens

| Token | Light | Dark |
|---|---|---|
| `--bg` | `#e9e6e0` | `#141312` |
| `--surface` | `#ffffff` | `#1b1a18` |
| `--surface-2` | `#f4f2ee` | `#232120` |
| `--line` | `rgba(0,0,0,.14)` | `rgba(255,255,255,.14)` |
| `--ink` | `#1b1a18` | `#e9e6e0` |
| `--ink-muted` | `#77736c` | `#8d8880` |
| `--accent` | `#d8552a` | `#ef6a3d` |
| `--accent-hover` | `#c04a22` | `#f37d55` |
| `--danger` | `#b22020` | `#e06666` |
| `--ok` | `#2f6f4e` | `#5bbd8c` |
| `--warn` | `#b8471f` | `#e0884f` |

Dark mode is the same markup with `data-theme="dark"` on `<html>`. Primary buttons in dark mode use dark ink on accent.

## Typography

Fonts: **IBM Plex Sans** (UI), **IBM Plex Mono** (short codes, URLs, keys, numbers), Architects Daughter only for prototype annotations (not shipped).

| Role | Size / weight |
|---|---|
| Display | 28 / 600, line-height 1.15, letter-spacing -0.025em |
| Title | 20 / 600 |
| Section | 15 / 600 |
| Body | 13 / 400, the reading size for forms and tables |
| Meta | 11.5 / 400, muted |
| Mono | 13 / 500 for `sho.rt/abc123` |
| Mono small | 11.5 / 400 for table cells and metadata |

## Spacing, radius, elevation

Spacing scale: 4, 8, 12, 16, 24, 32. Radius: 4 (inputs, chips), 6 (buttons, cards), 8 (panels), 12 (modals), 999 (pills). Elevation: `e-1: 0 1px 2px rgba(0,0,0,.08)`, `e-3: 0 8px 24px rgba(0,0,0,.14)`.

## Signature

The mark is a chevron `»` in accent color. Short codes are always displayed as `sho.rt»abc123` (chevron before the code, mono). Favicon: orange `»` on `#1b1a18`. GitHub social preview: dark ground, chevron at 220px, headline at 64px.

## Screens

| id | Screen | Notes |
|---|---|---|
| system | Design system | tokens, type, button and field states |
| landing | Landing page | static, GitHub stars injected at build |
| preview | Link preview (`/code+`) | static, no auth, no JS; Continue is a plain anchor |
| errors | Error pages | one template, 404 / 410 / 403 / 429, chevron "under stress" glyphs |
| auth | Magic link auth | email → inbox → signing in → expired |
| email | Magic link email | table-based, inline styles, 560px, no images |
| onboarding | Onboarding | create workspace, invite accept, 3-step first link |
| dashboard | Links list | quick-create strip, filter chips, table with sparklines, bulk bar |
| newlink | Create / edit link | metadata fetch, code check, UTM presets, device routing, social card |
| analytics | Link analytics | KPIs, chart, 6 breakdown panels, heatmap, recent clicks |
| overview | Workspace analytics | KPIs, chart, leaderboard, 3 panels |
| import | Bulk import | upload → mapping → validation table → progress → summary |
| settings | Workspace settings | general, members with role matrix, API keys, danger zone |
| account | Account settings | profile, theme, sessions |
| mobile | Mobile (390) | table → cards, sidebar → bottom tab bar, panels → tab strip, modals → sheets |
| dark | Dark mode | same markup, dark tokens |

## HTMX behavior notes (from the prototype)

- **Dashboard**: quick-create posts to `/links/quick`, swaps the result strip out-of-band and prepends the new row into `#link-rows`. Filters and sort use `hx-get /links?...` targeting `#link-rows` with `hx-push-url`. Copy is pure JS with a toast. QR opens a modal partial, the `⋯` menu is a dropdown partial, edit is a full page load. Bulk bar appears via out-of-band swap when any checkbox changes. Infinite scroll with `hx-trigger="revealed"`.
- **New link**: full page load. URL blur → `hx-post /links/metadata` fills title, favicon and OG defaults. Code field → `hx-get /links/check?code=` on `keyup changed delay:300ms`, swaps the availability line only. Preset chips → `hx-post /utm/preset`, swaps the four UTM inputs and the final URL. Platform switcher swaps the card preview partial. Device toggle swaps the routing rows and diagram. Submit posts the whole form; server re-renders with the error summary on failure.
- **Analytics**: full page load for the shell. Date range, granularity and bot toggle `hx-get` the analytics body with `hx-push-url`; one swap refreshes KPIs, chart data and every panel. Charts re-init from swapped JSON on `htmx:afterSwap`. Recent clicks list polls every 20 s. Export CSV is a plain link.
- **Auth**: email submit is a normal POST (works without JS). Resend is `hx-post /auth/resend` swapping the button and cooldown text. Magic URL GET redirects on success.
- **Settings**: left nav entries are separate URLs. Role select posts on change and swaps the row. Invite appends to the pending list via `hx-post` and shows a toast. Create key swaps in a show-once panel. Delete stays disabled until the typed slug matches.
- **Import**: upload is a real multipart POST. Mapping selects re-request the validation table with `hx-post /import/validate`. Progress polls every 2 s and stops once the server returns the summary partial.
- **Mobile**: 44px touch targets, full-height sheets for modals.
- **Dark**: Chart.js reads colors from CSS variables and re-renders on theme change.

## Sample data used in the prototype

UTM presets: Instagram bio, Instagram story, TikTok profile, YouTube description, Newsletter, Custom. Filter chips: Tags, Status, Date range, Device routing, Has UTM. Analytics panels: Referrers, Countries, Cities, Devices & OS, Browsers, UTM breakdown. Role matrix: create/edit links and view analytics (all), invite/manage members and API keys (owner, admin), delete/transfer workspace (owner).
