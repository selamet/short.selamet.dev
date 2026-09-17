# Claude Design Prompt — short

> Replace `short` with the final product name before pasting.

---

## Product context

Design the complete UI for **short**, an open-source, self-hostable URL shortener built for social media teams. Think "Bitly for people who post on Instagram and TikTok all day", but developer-grade, privacy-respecting and free to run on your own server.

It is a multi-user SaaS-style product: users sign up, create or join a **workspace**, and manage short links inside it. Every short link lives on one shared domain (e.g. `sho.rt/abc123`). The project is open source (GitHub), so the design must also work as the public face of the project: a landing page that sells the idea to both end users and self-hosters.

**Target users**
- Social media managers and creators who post links in Instagram bios, stories, TikTok, YouTube descriptions and newsletters.
- Small agencies managing several client workspaces.
- Developers who self-host it and integrate through the REST API or the browser extension.

**Three things that make it different from a generic shortener** (these must be visible in the UI, not buried):
1. **Social card control**: every link can override the Open Graph title, description and image, with a live preview of how the link card looks on WhatsApp, X, LinkedIn and Slack. Defaults are auto-fetched from the destination.
2. **Device-aware routing**: one short link can send iOS, Android and desktop visitors to different destinations, including native app deep links (e.g. open the Instagram app instead of the mobile web).
3. **UTM builder with platform presets**: one click applies "Instagram bio", "Instagram story", "TikTok profile", "YouTube description", "Newsletter" presets; the resulting UTM parameters are editable.

Plus solid analytics: total and unique clicks, time series, referrers, countries, devices, browsers, hour-of-day heatmap, bot filtering, CSV export.

## Tech constraints (respect these, they shape what is buildable)

- Server-rendered **Django templates + HTMX + Tailwind CSS**. No SPA. Design components as static HTML that can be enhanced with small HTMX swaps (inline edits, modals, partial reloads, toasts).
- Charts are rendered with **Chart.js**. Design chart styling (colors, gridlines, tooltips), but keep chart types to line, bar, horizontal bar, donut and a simple heatmap grid.
- Forms are standard HTML forms with server-side validation. Design inline field errors and a top-of-form error summary.
- Must support **light and dark mode** via a `data-theme` attribute and CSS variables.
- Responsive: desktop first, but every screen must work at phone width (link creation and analytics are used on mobile).
- Accessibility: WCAG AA contrast, visible focus rings, keyboard-navigable menus and modals.

## Design direction

Avoid the generic "purple gradient SaaS" look. The product should feel like a **precise, calm, utilitarian tool**: dense enough for power users, quiet enough to live in a browser tab all day. References for tone: Linear's density, Plausible Analytics' restraint, Raycast's crispness. A single confident accent color, neutral surfaces, strong typography hierarchy, generous use of monospace for short codes, URLs and API keys.

Give the product a small, memorable visual signature (a mark, a way short codes are displayed, a distinctive empty-state illustration style) that also works as a GitHub social preview and favicon.

Produce a **design system** first (color tokens for light and dark, type scale, spacing, radius, elevation, component states) and then apply it consistently across all screens below.

## Screens to design

### 1. Public / marketing
- **Landing page**: hero with the value proposition, the three differentiators shown with real UI snippets, an analytics screenshot, "Self-host in 5 minutes" section with a `docker compose up` snippet, GitHub stars / license badge, footer.
- **Public link preview page** (`sho.rt/abc123+`): shows where the link goes, the social card, created date, a "Continue" button. Used for trust when someone is unsure about a link.
- **Error pages**: link not found, link expired, link disabled, rate limited.

### 2. Authentication (magic link only, no passwords)
- Enter email → "Check your inbox" screen with resend and change-email actions.
- Magic link opened: brief "Signing you in" state.
- Invalid or expired link state.
- The email itself: a simple transactional email template containing the magic link button and a plain-text fallback.

### 3. Onboarding
- First-run: create your workspace (name, slug) → land on an empty dashboard with a guided empty state that walks through creating the first link.
- Accept-invite flow for users invited into an existing workspace.

### 4. Dashboard: links list (the home screen)
- Workspace switcher, global search, "New link" primary action.
- Quick-create bar at the top: paste a URL, get a short link instantly, expand for advanced options.
- Links table/list with: short code (monospace, copy button), destination (truncated, favicon), tags, clicks (7-day sparkline), created date, status (active/expired/disabled), row actions (copy, QR, edit, analytics, archive).
- Filters: tags, status, date range, sort. Bulk select with bulk actions (tag, archive, export).
- Empty state, loading state (HTMX partial swap), and a "no results" state for filters.

### 5. Create / edit link (full form)
Sections in one page or a stepped panel:
- Destination URL + auto-fetched title and favicon.
- Short code: random by default, custom slug with availability check, reserved-word error.
- Tags (create inline), optional internal note.
- **UTM builder**: platform preset chips (Instagram bio, Instagram story, TikTok, YouTube, Newsletter, Custom) that fill source/medium/campaign/content; editable fields; final URL preview.
- **Device routing**: toggle "Different destinations per device"; rows for iOS, Android, Desktop; optional "Open in app" deep link field with fallback URL. Show a small diagram of what happens on each device.
- **Social card**: fetched OG defaults, override title/description/image (upload or URL), live card preview with a platform switcher (WhatsApp, X, LinkedIn, Slack).
- Expiration: by date or by click count (design it even though it ships in phase 2; hide behind an "Advanced" disclosure).
- Save, Save & copy, Cancel. Validation states.

### 6. Link analytics (single link)
- Header with short link, destination, copy and QR actions, date range picker (7d, 30d, 90d, custom), "Exclude bots" toggle, Export CSV.
- KPI tiles: total clicks, unique clicks, top country, top referrer, with delta vs previous period.
- Clicks over time (line/bar, hourly or daily granularity).
- Breakdown panels: referrers, countries (with a list, no world map required), cities, devices, OS, browsers, UTM source/medium/campaign, and destination split for device-routed links.
- Hour-of-day × weekday heatmap.
- Recent clicks stream (anonymized: country, device, referrer, time).
- Empty state for a link with zero clicks.

### 7. Workspace analytics overview
- Same visual language as link analytics but aggregated: total clicks, top links leaderboard, clicks over time, top referrers and countries.

### 8. QR code modal
- Preview, size selector, foreground/background color, optional center logo, download PNG/SVG.

### 9. Bulk import
- Upload CSV, column mapping preview, validation results table (row-level errors), confirm import, progress state (processed in the background), completion summary.

### 10. Workspace settings
- General (name, slug, default UTM preset, timezone).
- Members: list with roles (Owner, Admin, Member), invite by email, pending invites, remove member, change role. Role permission matrix shown inline.
- API keys: create (show once), list with last used, revoke. A short "Getting started with the API" snippet with curl.
- Danger zone: transfer ownership, delete workspace (with confirmation pattern that avoids native browser dialogs).

### 11. Account settings
- Email, display name, theme (system/light/dark), active sessions, delete account.

### 12. Global patterns
- Navigation (sidebar on desktop, bottom or drawer on mobile).
- Modals, slide-over panels, dropdown menus, toasts (success, error, info), confirmation dialogs.
- Tables and list rows at phone width.
- Copy-to-clipboard feedback pattern used everywhere short links appear.

## Deliverables

1. Design system: tokens (light + dark), typography, spacing, components with states (default, hover, focus, active, disabled, error, loading).
2. All screens above at desktop (1440) and mobile (390) widths, in both themes for at least the dashboard, link form and analytics screens.
3. Component annotations that explain HTMX-friendly behavior (what swaps, what opens as a panel, what is a full page load).
4. A GitHub social preview image (1280×640) and an app icon/favicon set.
5. Exportable CSS variables for the tokens so they can be dropped into Tailwind's config.

Where you have to choose, prefer clarity and speed of use over decoration. This is a tool people use fifty times a day.
