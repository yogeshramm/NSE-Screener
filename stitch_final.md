# YOINTELL — Professional Stock Intelligence Platform (Final Spec)

Design a single-page web application for an advanced NSE stock screener called **"YOINTELL"**. This is a professional-grade predictive stock analysis platform competing with Koyfin, TradingView, and Bloomberg Terminal — built with a modern AI-native aesthetic. It must look like it was designed and built by a $50M fintech startup's 10-person design team.

**Design references to emulate:**
- Koyfin's clean data density and institutional feel
- TradingView's charting elegance and dark theme (#131722 background, #2962FF accent)
- Linear.app's glassmorphism and micro-interactions
- Vercel dashboard's typography and spacing precision
- Stripe's developer-friendly clean layouts
- Bloomberg Terminal's information hierarchy (but with modern UI)

**UX Psychology Principles Applied Throughout:**
- Reduce cognitive load: group related controls, use progressive disclosure (collapsible sections), show only what matters at each step
- Fitt's Law: primary actions (Screen, Add, Check Alerts) are large, high-contrast, easy to target
- Recognition over recall: status badges, color-coded scores, visual icons — user never has to remember what numbers mean
- Feedback loops: every click produces immediate visual feedback (glow, animation, state change)
- Gestalt proximity: related items grouped with consistent spacing; unrelated sections separated by clear dividers
- Information scent: users can always tell where to go next via visual hierarchy and accent colors guiding the eye

---

## GLOBAL DESIGN SYSTEM

### Color Palette (EXACT hex values)
```
Background:           #0A0E1A (deep navy-black, NOT pure black)
Surface Level 1:      #111827 (card backgrounds)
Surface Level 2:      #1A1F2E (elevated cards, headers)
Surface Level 3:      #242938 (inputs, dropdowns, hover states)
Surface Level 4:      #2E3348 (borders, dividers, scrollbar thumb)

Primary Accent:       #00E5A0 (electric teal-green — main CTA, active states)
Primary Glow:         rgba(0, 229, 160, 0.15) (ambient glow on buttons)
Primary Muted:        rgba(0, 229, 160, 0.10) (enabled chip backgrounds)
Primary Border:       rgba(0, 229, 160, 0.30) (active borders)

Secondary Accent:     #60A5FA (blue — Stage 2, run button, links)
Secondary Alt:        #ADC6FF (light blue — Stage 2 ranks)

Violet Accent:        #8B5CF6 (purple — fundamental category, hidden gem tier)
Amber Accent:         #F59E0B (gold — breakout category, most precise tier, star icons)
Amber Warning:        #FFB800 (borderline status)

Success/Bullish:      #00E5A0 (same as primary)
Error/Bearish:        #FF6B6B (soft coral red, NOT harsh red)
Danger Active:        rgba(255, 107, 107, 0.20) (stop button background)

Text Primary:         #E8ECF4 (headings, stock symbols)
Text Secondary:       #94A3B8 (labels, descriptions, slate-400)
Text Muted:           #64748B (timestamps, disabled text, slate-500)
Text Dim:             #475569 (placeholders, inactive, slate-600)
```

### Typography
```
Font Family:          'Inter', -apple-system, BlinkMacSystemFont, sans-serif
Font Feature:         font-feature-settings: 'tnum' 1 (tabular numbers for data alignment)

Page Titles:          24px, weight 700, text-primary
Section Headers:      12px, weight 700, uppercase, letter-spacing 0.05em, text-secondary
Table Headers:        11px, weight 500, text-secondary
Table Data:           11px, weight 400, text-primary (12px for prices/scores)
Badge Text:           10px, weight 700, uppercase
Chip Labels:          9px, weight 700, uppercase
Tiny Labels:          9px, weight 400, text-muted
Parameter Values:     10px, weight 700, monospace feel
```

### Spacing & Sizing
```
Nav Height:           56px (fixed, z-50)
Page Padding:         16px (screener), 24px (config/indicators/watchlist)
Card Padding:         16px
Card Border Radius:   12px (cards), 8px (buttons/inputs), 20px (badges/pills)
Chip Padding:         4px 8px
Table Row Height:     40px
Table Cell Padding:   8px horizontal, 8px vertical
Gap between cards:    12px
Filter Panel Height:  120px collapsed, 400px expanded (smooth 300ms transition)
Side Panel Width:     400px
Chart Panel Split:    Tables shrink to 320px, chart fills remaining width
Chat Panel:           380px × 520px
```

### Effects & Animations
```
Card Background:      backdrop-filter: blur(20px); background: rgba(17, 24, 39, 0.80); border: 1px solid rgba(46, 51, 72, 0.50)
Glass Effect:         backdrop-filter: blur(16px); background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.06)
Button Glow:          box-shadow: 0 0 20px rgba(0, 229, 160, 0.15), 0 0 40px rgba(0, 229, 160, 0.05)
Highlighted Glow:     box-shadow: 0 0 8px rgba(0, 229, 160, 0.25)
Transition Speed:     200ms ease for hover, 300ms ease for panels/toggles
Scrollbar:            width: 6px, border-radius: 10px, thumb: #2E3348, track: #0A0E1A
Active Tab Indicator: 2px solid bottom border with gradient matching logo gradient
Pulse Animation:      @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.5 } }
Glow Animation:       @keyframes glow-pulse { 0%,100% { box-shadow: 0 0 8px rgba(0,229,160,0.3) } 50% { box-shadow: 0 0 20px rgba(0,229,160,0.6) } }
Spin Animation:       @keyframes spin { to { transform: rotate(360deg) } }
Gradient Shift:       @keyframes gradient-shift { 0% { background-position: 0% 50% } 50% { background-position: 100% 50% } 100% { background-position: 0% 50% } }
Bounce Dot:           @keyframes bounce-dot { 0%,80%,100% { transform: translateY(0) } 40% { transform: translateY(-8px) } }
```

### Hover Dynamism & Micro-Interactions (Global)

Apply premium, psychologically satisfying micro-interactions everywhere:

**Table rows (Stage 1, Stage 2, Watchlist, Config, Filter Inspector):**
- Hover: background rgba(0,229,160,0.03), transform translateX(2px), transition 200ms ease
- A 2px left-border accent in #00E5A0 fades in on hover
- Cursor: pointer (on clickable rows)

**Cards (Indicators tab, Config tab):**
- Hover: translateY(-2px), box-shadow 0 8px 24px rgba(0,0,0,0.3), border-color transitions to rgba(0,229,160,0.15)
- Transition: all 200ms ease

**All buttons:**
- Primary (gradient) buttons: hover scale(1.03) + shadow intensification
- Icon-only buttons: hover color #94A3B8 → #00E5A0 + scale(1.1)
- Text links: hover underline-offset 4px + color transition
- Click: brief scale(0.97) snap-back (tactile micro-feedback)

**Filter chips:**
- Hover on disabled chip: border brightens to rgba(0,229,160,0.15), scale(1.02)
- Hover on enabled chip: glow intensifies
- Click: scale(0.97) for 100ms then snap back

**Tab buttons (nav):**
- Hover: bottom border appears at 50% opacity before full switch

**Download ring:** hover scale(1.1) with subtle glow
**Sync button:** hover icon rotates 180deg, background brightens
**Avatar:** hover ring glow around it

### Icon System
- Use Google Material Symbols Outlined (weight 400, fill 0, grade 0, optical size 24)
- Icons referenced below by their material name
- Default size: 20px for nav, 16px for inline, 14px for table actions, 12px for tiny

---

## LOGIN / REGISTER PAGE (Shown First)

Full-page auth overlay shown before the app loads. Hides the entire app until user is authenticated.

**Auth Overlay** (`id="auth-page"`):
- Position: fixed, inset 0, z-index 100 (above everything)
- Display: flex, items-center, justify-center
- Background: #0A0E1A with animated ambient mesh:
  ```css
  background-image:
    radial-gradient(ellipse at 20% 50%, rgba(0,229,160,0.04) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 20%, rgba(96,165,250,0.04) 0%, transparent 50%),
    radial-gradient(ellipse at 50% 80%, rgba(139,92,246,0.03) 0%, transparent 50%);
  ```
  These gradient blobs slowly drift (CSS animation moving background-position over 15s)

**Login Card (centered):**
- Width: 400px, padding 40px, border-radius 20px
- Background: rgba(17,24,39,0.80), backdrop-filter blur(20px)
- Border: 1px solid rgba(46,51,72,0.40)
- Box-shadow: 0 24px 64px rgba(0,0,0,0.5)
- Entry animation: fade-in + translateY(20px → 0) over 400ms

**Card contents (top to bottom):**

1. **Logo:** "YOINTELL" with animated gradient (same as nav, but 28px weight 900)
   - Tagline below: "Predictive Stock Intelligence" — 11px, #475569, uppercase, letter-spacing 0.1em
   - Margin-bottom 36px

2. **Tab toggle (Login / Register):**
   - Container: background #0A0E1A, border-radius 10px, padding 4px, full width, flex
   - Two equal-width pills:
     - Active: background #1A1F2E, color #E8ECF4, weight 600, border-radius 8px
     - Inactive: background transparent, color #64748B
   - Font: 13px. Transition background/color 200ms.
   - Default: Login active

3. **Login Form** (`id="login-form"`, visible when Login tab active):

   **Username field:**
   - Label: "USERNAME" — 10px, #94A3B8, uppercase, weight 600, letter-spacing 0.05em, margin-bottom 6px
   - Input container: flex, items-center, background #0A0E1A, border 1px solid #2E3348, border-radius 10px, padding 0 14px
     - Left icon: material `person` (16px, #475569)
     - Input: flex-grow, background transparent, no border, padding 12px 8px, font-size 14px, color #E8ECF4
     - Placeholder: "Enter username" in #475569
   - Focus state: border-color #00E5A0, box-shadow 0 0 0 3px rgba(0,229,160,0.08)
   - Margin-bottom 16px

   **Password field:** (same structure)
   - Left icon: material `lock` (16px, #475569)
   - Placeholder: "Enter password"
   - Right icon: material `visibility` / `visibility_off` (16px, #475569) — toggle to show/hide password
   - Margin-bottom 24px

   **Login button:**
   - Full width, padding 14px, border-radius 10px
   - Background: linear-gradient(135deg, #00E5A0, #00B4D8)
   - Color: #0A0E1A, 14px weight 700
   - Box-shadow: 0 0 20px rgba(0,229,160,0.15)
   - Hover: shadow intensifies, scale(1.02)
   - Loading: gradient shifts to animated pulse, text replaced by 3-dot bounce animation
   - Text: "Sign In"

   **Error message** (`id="auth-error"`):
   - Hidden by default
   - When shown: 12px, #FF6B6B, text-center, margin-top 12px, fade-in animation

4. **Register Form** (`id="register-form"`, hidden when Login tab active):
   - **Display name field:** same styling, icon `badge`, placeholder "Display name"
   - **Username field:** same as login
   - **Password field:** same as login
   - **Confirm password field:** same styling, icon `lock`, placeholder "Confirm password"
   - **Register button:** same gradient style, text "Create Account"

5. **Footer:** "Built with precision for Indian markets" — 10px, #475569, text-center, margin-top 28px

**Authentication behavior:**
- On page load: check localStorage for "yointell_token"
- If token exists → call GET /auth/me. If valid → hide auth page, show app. If expired → show auth page.
- If no token → show auth page
- On login success → store token in localStorage, hide auth page with fade-out, show app with fade-in
- On logout → clear token from localStorage, show auth page

---

## PAGE STRUCTURE: SINGLE HTML FILE WITH 4 TABS

The entire application is one page with tab-based navigation. Only one tab is visible at a time. Tab content areas use `display: none` / `display: block` toggling.

**Page initial load animation:**
- "YOINTELL" types out letter-by-letter (typewriter, 1.2s total)
- Then gradient animation begins on the logo
- Brief fade-in of all content (300ms) after logo completes

---

## NAVIGATION BAR (Fixed top, 56px, full width)

**Background:** rgba(10, 14, 26, 0.80) with backdrop-blur-xl (16px blur)
**Border:** 1px solid rgba(46, 51, 72, 0.20) on bottom edge
**Layout:** flex, justify-between, items-center, horizontal padding 24px

### Left Section

- **Logo Container** (flex column):
  - **Primary text:** "YOINTELL" — 20px, weight 900, letter-spacing -0.04em
  - Apply CSS animated gradient:
    ```css
    .logo-text {
      background: linear-gradient(135deg, #00E5A0 0%, #00B4D8 40%, #8B5CF6 70%, #00E5A0 100%);
      background-size: 200% 200%;
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      animation: gradient-shift 4s ease infinite;
    }
    ```
  - **Tagline below logo:** "Predictive Stock Intelligence" — 8px, weight 500, letter-spacing 0.12em, uppercase, color #475569
  - **On first page load:** Logo text types out letter-by-letter (typewriter effect over 1.2 seconds), then gradient animation begins
  - **On hover:** brightness 1.2, subtle scale(1.02), 300ms transition

- **Tab Buttons** (hidden below md breakpoint, flex row, gap 20px, margin-left 32px):
  1. **"Screener"** — `id="tab-btn-screener"` — Active by default
  2. **"Configuration"** — `id="tab-btn-config"`
  3. **"Indicators"** — `id="tab-btn-indicators"`
  4. **"Watchlist"** — `id="tab-btn-watchlist"`

  **Active state:** text #00E5A0, 2px solid bottom border with gradient matching logo gradient, padding-bottom 4px
  **Inactive state:** text #94A3B8, no border
  **Hover (inactive):** text #00E5A0, bottom border appears at 50% opacity, 200ms transition
  **Font:** 14px, weight 500

### Right Section (flex, items-center, gap 12px)

#### Circular Progress Ring (`id="download-ring"`)
- **Size:** 36px × 36px SVG
- **Structure:** Two concentric circles (radius 15, stroke-width 3)
  - Background circle: stroke #2E3348
  - Foreground circle (`id="ring-fg"`): stroke #00E5A0, stroke-linecap round
  - Uses stroke-dasharray (circumference = 94.25) and stroke-dashoffset for animation
  - SVG rotated -90deg so progress starts from top
- **Center text** (`id="ring-text"`): 8px, weight 700, color #00E5A0
  - Shows: "0%" → percentage during download → "✓" when complete
- **Ring color states:** #2E3348 (0%), #46F1C5 (downloading), #00E5A0 (100%)
- **Clickable** — cursor pointer, onclick triggers data sync
- **Tooltip:** "Click to download data"
- **Hover:** scale(1.1) with subtle glow
- **Data status states:**
  - **Synced:** green pulsing dot (4px) next to "Synced" text, ring shows ✓
  - **Downloading:** animated ring sweep with sweeping dash effect, percentage text pulses subtly, "Downloading..." with animated ellipsis
  - **Offline:** red dot (4px) + "Server offline" in #FF6B6B + tiny text "Start server" in #475569

#### Data Status Labels (flex column, gap 0)
- `id="data-status"`: "2619 stocks cached" — 10px, text-muted (#64748B)
- `id="data-date"`: "Data as of: 2026-04-14" — 10px, text #00E5A0, weight 700
- `id="data-detail"`: "2,619 stocks | 271 days" — 9px, text-dim (#475569)

#### Sync Button (`id="dl-btn"`)
- Background: #242938, hover: #2E3348
- Text (`id="dl-btn-text"`): "Sync" / "Synced" / "Download Data" / "Download History" / "Downloading..." / "Syncing..." / "Up to date" / "Full setup..."
- Icon: material `sync` (rotates when syncing)
- Font: 12px, weight 700, text #00E5A0
- Border-radius: 8px, padding: 6px 12px
- When synced: text changes to #64748B (muted)
- Hover: icon rotates 180deg, background brightens

#### Profile Avatar Button
- 32px × 32px circle, background: linear-gradient(135deg, #00E5A0, #60A5FA)
- Shows first letter of display_name (14px, weight 700, color #0A0E1A, centered)
- Cursor pointer
- Hover: ring glow (box-shadow 0 0 0 3px rgba(0,229,160,0.20))
- On click: toggles profile dropdown

**Profile dropdown:**
- Position: absolute, top 52px, right 24px
- Width: 220px, background #1A1F2E, border-radius 12px, border 1px solid #2E3348
- Box-shadow: 0 8px 24px rgba(0,0,0,0.4)
- Padding: 8px
- Entry animation: fade-in + translateY(-8px → 0) over 200ms
- **User info:** display_name (14px, weight 600, #E8ECF4) + username below (11px, #64748B)
- **Divider:** 1px solid #2E3348, margin 8px 0
- **Logout row:** flex, items-center, gap 8px, padding 8px 12px, border-radius 8px, cursor pointer
  - Icon: material `logout` (16px, #FF6B6B)
  - Text: "Logout" — 13px, #FF6B6B
  - Hover: background rgba(255,107,107,0.08)
- **Click outside** dropdown: closes it

---

## TAB 1: SCREENER (`id="tab-screener"`)

**Container:** margin-top 56px (below nav), padding 16px, height calc(100vh - 56px), overflow-y auto

### 1.1 FILTER PANEL (Collapsible card at top)

**Outer container:** background #111827, border-radius 12px, margin-bottom 16px, overflow hidden

#### Filter Panel Header Bar
- **Background:** #1A1F2E
- **Border-bottom:** 1px solid rgba(46, 51, 72, 0.20)
- **Padding:** 8px 12px
- **Layout:** flex, justify-between, items-center

**Left side:**
- Material icon `tune` (16px, #00E5A0)
- Text "ACTIVE FILTERS" — 12px, weight 700, #94A3B8
- Count badge (`id="filter-count"`): e.g., "32/44" — 9px, weight 700, background rgba(0,229,160,0.20), text #00E5A0, padding 2px 6px, border-radius 20px

**Right side (flex, gap 8px, items-center):**
1. **Preset Dropdown** (`id="screener-preset-select"`):
   - Background: #242938, no border, border-radius 8px
   - Text: 9px, #00E5A0
   - Padding: 2px 8px
   - Default option: "Preset..."
   - Populated dynamically with saved preset names
   - onchange: loads selected preset, applies to filter config, re-renders chips

2. **Active Preset Badge** (`id="active-preset-badge"`):
   - Hidden by default
   - When visible: shows "presetname ×" — 9px, weight 700
   - Background: rgba(0,229,160,0.20), text #00E5A0
   - Padding: 2px 6px, border-radius 20px
   - Clickable — clicking clears the active preset and resets dropdown
   - The × is a literal multiplication sign character

3. **Quick Save Button** (onclick: prompts for name, saves current filter config):
   - Material icon `save` (12px, #94A3B8, hover: #00E5A0)
   - Title tooltip: "Save current as preset"

4. Separator: "|" in #475569

5. **"Enable All"** — 9px, text #00E5A0, hover underline. Enables all 44 filters.

6. Separator: "|"

7. **"Disable All"** — 9px, text #94A3B8, hover underline. Disables all 44 filters.

8. Separator: "|"

9. **Expand/Collapse Toggle** (`id="filter-toggle-btn"`):
   - Material icon (`id="filter-expand-icon"`): `expand_more` / `expand_less`
   - Color: #94A3B8, hover: #00E5A0

#### Filter Panel Body (`id="filter-panel"`)
- **Padding:** 12px
- **Layout:** flex, flex-wrap, gap 6px, items-center
- **Height:** max-height 120px (collapsed), 400px (expanded), overflow-y auto, transition max-height 300ms ease
- **Initial state:** "Loading filters..." text in #64748B

**Populated dynamically with 3 category sections:**

**Section 1: TECHNICAL (19 filters)**
- Label: "▎TECHNICAL" — 9px, weight 700, uppercase, letter-spacing 0.05em, color #60A5FA (blue)
- Full-width div, margin-bottom 4px
- Chips container: flex, flex-wrap, gap 6px, full width, margin-bottom 8px
- Filters (in order): ema, rsi, macd, volume_surge, supertrend★, adx, obv, cmf, roc, awesome_oscillator, anchored_vwap, pivot_levels, hidden_divergence, sector_performance, fisher_transform, klinger_oscillator, chande_momentum, force_index, vortex★

**Section 2: FUNDAMENTAL (11 filters)**
- Label: "▎FUNDAMENTAL" — same style but color #8B5CF6 (violet)
- Filters: roe, roce, debt_to_equity, eps, free_cash_flow, institutional_holdings, analyst_ratings, earnings_blackout, pe_ratio, daily_turnover, free_float

**Section 3: BREAKOUT & RISK (14 filters)**
- Label: "▎BREAKOUT & RISK" — same style but color #F59E0B (amber)
- Filters: breakout_proximity, breakout_volume, breakout_rsi, breakout_candle, supply_zone, institutional_flow, bb_squeeze, stochastic_rsi, williams_r, vwap_bands★, ichimoku, late_entry_stage1, late_entry_stage2, risk_management

#### Individual Filter Chip Structure (`id="chip-{filterKey}"`)
Each chip is a small inline-flex container:
- **Layout:** flex, items-center, gap 4px
- **Padding:** 4px 8px
- **Border-radius:** 8px
- **Cursor:** pointer
- **Transition:** all 200ms ease

**Contents (left to right):**
1. Star icon (only for ★ highlighted filters: supertrend, vwap_bands, vortex): "⭐" in 8px
2. Checkbox: 12px × 12px, rounded, no border, no focus ring
   - Checked color: #00E5A0
   - Background when unchecked: #242938
   - onChange: toggles this filter's enabled state, re-renders panel
3. Filter label: 9px, uppercase, weight 700
   - Enabled: text #00E5A0
   - Disabled: text #64748B
   - Clickable — toggles filter on/off
   - Label is the filter key with underscores replaced by spaces (e.g., "volume_surge" → "VOLUME SURGE")
4. Parameter value input (only if filter has parameters):
   - Shows the FIRST parameter's current value (e.g., RSI period=14, EMA fast_ema_period=50)
   - Styling: transparent background, no border, 10px, weight 700, width 32px, text-right, no focus ring
   - Enabled: text #00E5A0, Disabled: text #475569
   - onChange: updates the parameter value in config

**Chip visual states:**
- **Highlighted + Enabled:** border 1px solid #00E5A0, box-shadow 0 0 8px rgba(0,229,160,0.25), background rgba(0,229,160,0.20)
- **Highlighted + Disabled:** border 1px solid rgba(0,229,160,0.40), background rgba(36,41,56,0.50)
- **Normal + Enabled:** border 1px solid rgba(0,229,160,0.30), background rgba(0,229,160,0.10)
- **Normal + Disabled:** border 1px solid #2E3348, background rgba(36,41,56,0.50)

### 1.2 SEARCH BAR (Below filter panel, above result tables)

A prominent, dedicated search section placed between the filter panel and the result tables. Not buried inside any other bar.

**Search Section (full-width glassmorphic bar):**
- Background: rgba(17, 24, 39, 0.50), backdrop-filter blur(12px)
- Border: 1px solid rgba(46, 51, 72, 0.30), border-radius 12px
- Padding: 10px 16px, margin-bottom 12px
- Layout: flex row, items-center, gap 12px

**Contents (left to right):**

1. **Search icon:** material `search` (20px, #475569) — non-interactive, visual anchor

2. **Search input** (`id="symbols-input"`):
   - Flex-grow, background transparent, no border, no outline
   - Font: 14px, weight 400, color #E8ECF4
   - Placeholder: "Search any stock... RELIANCE, TCS, HDFCBANK" — color #475569
   - On focus: placeholder text fades to 30% opacity
   - onkeydown: pressing Enter triggers the search/screen
   - Accepts comma-separated symbols (e.g., "RELIANCE, TCS, INFY")

3. **Vertical divider:** 1px × 28px, background #2E3348

4. **Scope pills** (3 pills in a row — ALL THREE must be present):
   - **"Nifty 200"** | **"Nifty 500"** (default active) | **"All NSE"**
   - Each pill: padding 4px 14px, border-radius 20px, font-size 11px, weight 600, cursor pointer
   - **Active pill:** background #00E5A0, color #0A0E1A, box-shadow 0 0 8px rgba(0,229,160,0.20)
   - **Inactive pill:** background transparent, border 1px solid #2E3348, color #94A3B8
   - **Hover (inactive):** border-color #00E5A0, color #00E5A0, transition 200ms
   - Clicking a pill activates it (others deactivate). Mutually exclusive selection.

5. **Vertical divider:** same as above

6. **"Screen" button** (`id="scan-all-btn"`):
   - Background: linear-gradient(135deg, #00E5A0, #00B4D8)
   - Color: #0A0E1A, font-size 13px, weight 700
   - Padding: 8px 22px, border-radius 20px, white-space nowrap
   - Icon: material `radar` (16px) — on hover, icon rotates 90deg over 300ms
   - Box-shadow: 0 0 20px rgba(0,229,160,0.20)
   - Hover: shadow → 0 0 30px rgba(0,229,160,0.35), scale(1.03), transition 200ms
   - During scan: text changes to "Scanning...", disabled, icon spins continuously
   - After scan: restores to "Screen" with radar icon

7. **"Run" button** (`id="run-btn"`):
   - Only visually prominent when search input contains text
   - Background: #60A5FA, color white, same pill shape (border-radius 20px, padding 8px 22px)
   - Icon: material `bolt` (16px)
   - Hover: scale(1.05)
   - If symbol input is empty and this is clicked: triggers full scope screen instead

### 1.3 LOADING STATE (`id="loading"`)

- **Default:** display none
- **Active:** display flex, flex-column, items-center, justify-center, padding 32px top/bottom

**AI-themed triple ring animation (centered):**
- Outer ring: 44px, 2px border rgba(0,229,160,0.12), rotating clockwise 3s
- Middle ring: 30px, 2px border rgba(0,229,160,0.25), rotating counter-clockwise 2s
- Inner ring: 18px, 2px border #00E5A0, rotating clockwise 1.5s
- Center dot: 4px solid #00E5A0, pulsing opacity
- Below rings: text with typewriter animation — "Analyzing stocks..." characters appear one by one (14px, #94A3B8)
- Then: progress text "Screening 127 / 500 stocks..." updates live during scan
- Below that: Stop button "Stop Screening" — margin-top 12px, padding 6px 16px, background rgba(255,107,107,0.20), text #FF6B6B, 12px weight 700, border-radius 8px, hover: background rgba(255,107,107,0.30)
- Stop button cancels the in-progress fetch via AbortController

### 1.4 RESULTS AREA — SPLIT LAYOUT (`id="main-split"`)

**Layout:** flex, gap 0, height calc(100vh - 280px)

#### LEFT: Tables Panel (`id="tables-panel"`)
- **Default width:** 100%
- **When chart open:** width 320px, min-width 320px
- **Transition:** width 300ms ease
- **Overflow-y:** auto
- **Contains two stacked table cards with 12px gap**

##### Stage 1: Swing Base Table
**Card:** background #111827, border-radius 12px, overflow hidden

**Header bar:**
- Background: #1A1F2E
- Border-bottom: 1px solid rgba(46,51,72,0.30)
- Padding: 8px
- Left: 1.5px × 1.5px pulsing green dot (animate-pulse) + "STAGE 1: SWING BASE" in 12px, weight 700, #00E5A0, uppercase
- Right: count badge (`id="s1-count"`): "0 results" — 10px, #64748B, background #2E3348, padding 2px 8px, border-radius 4px

**Empty state (before any screening):**
- Centered content: material `radar` (48px, #2E3348) + "Run a screen to discover swing candidates" (14px, #475569) + "Select filters and click Screen, or search specific stocks" (11px, #2E3348)

**Table:** full width, text-align left, font-size 11px
**Column headers** (border-bottom 1px solid rgba(46,51,72,0.20)):

| Column | Align | Width | Notes |
|--------|-------|-------|-------|
| # | left | auto | Rank number |
| Stock | left | auto | Symbol (bold) + sector (9px, muted, below) |
| Price | right | auto | ₹ prefix |
| PE | right | wider | table-col-wide class |
| RSI | right | wider | table-col-wide class |
| ROE% | right | wider | table-col-wide class |
| Score | right | auto | Bold |
| Status | center | auto | PASS/FAIL badge |
| (bookmark) | center | 24px | No header text, just empty th |

**Row template for each result:**
```
Row: hover bg rgba(0,229,160,0.03), translateX(2px), 2px left-border accent fades in
Cursor pointer, border-bottom 1px solid rgba(46,51,72,0.10)
onClick: opens chart panel on right side

Column 1 (#): font-bold, if passed → text #00E5A0, if failed → text #64748B. Shows "#1", "#2", etc.
Column 2 (Stock):
  Line 1: symbol name, font-bold (e.g., "RELIANCE")
  Line 2: sector, 9px, text #64748B (e.g., "Energy")
Column 3 (Price): "₹1315.18" right-aligned
Column 4 (PE): "18.2" or "--" if missing
Column 5 (RSI): value from fundamentals or "--"
Column 6 (ROE%): "28.8%" or "--"
Column 7 (Score): bold (e.g., "41.7")
Column 8 (Status): pill badge
  PASS: background rgba(0,229,160,0.15), text #00E5A0, 10px, weight 700, padding 2px 8px, rounded-full
  FAIL: background rgba(255,107,107,0.15), text #FF6B6B, same styling
Column 9 (Bookmark): material icon bookmark_add (14px, #64748B, hover #00E5A0)
  onClick (with event.stopPropagation to not trigger row click): adds stock to watchlist
  Title tooltip: "Add to Watchlist"
```

##### Stage 2: Breakout Table
**Same card structure as Stage 1, but:**
- Header dot: NOT pulsing, color #ADC6FF (light blue)
- Header text: "STAGE 2: BREAKOUT" in #ADC6FF
- Count badge: `id="s2-count"`

**Empty state (before any screening):**
- Material `trending_up` (48px, #2E3348) + "Breakout candidates appear after Stage 1" (14px, #475569)

**Columns:**

| Column | Align | Notes |
|--------|-------|-------|
| # | left | Rank, text #ADC6FF (blue) |
| Stock | left | Symbol only, bold |
| Price | right | ₹ prefix |
| SL | right | Stop Loss, text #FF6B6B (red) |
| Target | right | text #00E5A0 (green) |
| R:R | center | "1:3.2" format, bold |
| Score | right | bold |
| Status | center | PASS/FAIL badge |
| (bookmark) | center | Same as Stage 1 |

#### RIGHT: Chart Panel (`id="chart-panel"`)
- **Default:** display none, width 0
- **When open:** display flex (column), width calc(100% - 330px)
- **Background:** #111827, border-radius 12px, overflow hidden
- **Left border:** 1px solid rgba(46,51,72,0.30)

**Chart Header Bar:**
- Background: #1A1F2E, padding 8px, border-bottom
- Left: material `candlestick_chart` (16px, #00E5A0) + symbol name (`id="chart-title"`, 12px bold #00E5A0) + price (`id="chart-price"`, 12px #94A3B8)
- Right: "Insights" button (material `psychology` 16px + text, 9px #94A3B8, hover #00E5A0) + Close button (material `close`, #94A3B8 hover white)

**Chart Indicator Toolbar (between header and chart body):**
- Layout: flex, gap 4px, items-center, padding 4px 8px

1. **"Indicators" button:**
   - Text: "Indicators" with material `ssid_chart` icon (14px)
   - Font: 10px, weight 600, color #94A3B8, hover color #00E5A0
   - Padding: 4px 8px, border-radius 6px, border 1px solid #2E3348
   - On click: opens indicator picker dropdown below

2. **Active indicator pills** (shown inline in toolbar):
   - Small removable pills for each active overlay
   - e.g., [EMA 50 ×] [EMA 200 ×] [Supertrend ×]
   - Each pill: 9px weight 600, padding 2px 6px, border-radius 10px
   - Background: rgba(0,229,160,0.10), text #00E5A0, border 1px solid rgba(0,229,160,0.20)
   - × button on each pill: 8px, hover color #FF6B6B — clicking removes that overlay from chart
   - Pill appears with fade-in animation when added

3. **Indicator Picker Dropdown** (opens below the Indicators button):
   - Position: absolute, below button, z-index 50
   - Width: 280px, max-height 320px, overflow-y auto
   - Background: #1A1F2E, border 1px solid #2E3348, border-radius 10px, box-shadow 0 8px 24px rgba(0,0,0,0.4)
   - Padding: 8px

   **Search input at top:**
   - Placeholder: "Search indicators..." — 11px, full width
   - Filters the list below as user types

   **Categorized indicator list:**
   - **Section: "Overlays"** (label 9px, #94A3B8, uppercase)
     - EMA 50, EMA 200, Supertrend, Bollinger Bands, Ichimoku Cloud, VWAP
   - **Section: "Oscillators"** (label)
     - RSI, MACD, Stochastic RSI, Williams %R, CMF, ADX, ROC, Vortex, Awesome Oscillator
   - **Section: "Volume"** (label)
     - Volume, OBV, Klinger, Force Index

   **Each row in list:**
   - Checkbox (checked = active on chart) + indicator name (12px) + status dot (green if on chart)
   - Hover: background rgba(0,229,160,0.05)
   - Clicking toggles the indicator on/off on the chart
   - When toggled on: pill appears in toolbar, overlay/panel appears on chart
   - When toggled off: pill removed, overlay removed

   **Click outside dropdown: closes it**

**Overlay/Panel behavior:**
- **Overlay indicators** (EMA, Supertrend, Bollinger, Ichimoku, VWAP): drawn ON the candlestick chart
- **Oscillator indicators** (RSI, MACD, Stochastic, etc.): shown as SEPARATE sub-panels below the candlestick chart, each 70-80px height
- **Volume indicators** (OBV, Klinger): shown as sub-panels below oscillators
- Sub-panels stack vertically, each with its own label and values
- All sub-panels share the same time axis (synced crosshair with main chart)
- Maximum 3 sub-panels visible at once (scroll for more)
- Each sub-panel has a tiny × button in its top-right corner to remove it

**Chart Body (vertically stacked panels):**

1. **Candlestick Chart** (`id="chart-container"`, height 60%):
   - Library: TradingView Lightweight Charts 4.1.0
   - Background: #111827 (matches card)
   - Grid lines: #1A1F2E (barely visible)
   - Candle colors: Up=#00E5A0, Down=#FF6B6B (matching app palette)
   - Border/wick colors: same as candle fill
   - Crosshair: mode 0 (follows cursor)
   - **Default overlay lines:**
     - EMA 50: color #F59E0B (amber/yellow), lineWidth 1, title "EMA50"
     - EMA 200: color #60A5FA (blue), lineWidth 1, title "EMA200"
     - Supertrend: color #00E5A0 (primary), lineWidth 2, solid, title "ST"
   - timeScale.fitContent() called after data load
   - **ResizeObserver** attached: auto-adjusts chart width when panel resizes

2. **RSI Sub-panel** (border-top, label "RSI (14)" in 9px #64748B uppercase):
   - Container `id="rsi-container"`, height 80px
   - RSI line: color #A855F7 (purple), lineWidth 1.5
   - Reference levels: 70 (red dashed #FF6B6B at 44% opacity), 30 (green dashed #00E5A0 at 27% opacity)
   - Synced time range with main chart
   - Tiny × button in top-right to remove

3. **Volume Sub-panel** (border-top, label "Volume" in 9px #64748B uppercase):
   - Container `id="vol-container"`, height 60px
   - Histogram series with volume price format
   - Bar colors: green (#00E5A0) for up days, red (#FF6B6B) for down days
   - Synced time range with main chart
   - Tiny × button in top-right to remove

**Cross-chart sync:** Main chart's timeScale.subscribeVisibleTimeRangeChange syncs all sub-panel time ranges

### 1.5 AI INSIGHTS SIDE PANEL (`id="side-panel"`)

- **Position:** fixed, right 0, top 56px (below nav)
- **Size:** width 400px, height calc(100vh - 56px)
- **Background:** #111827
- **Border-left:** 1px solid rgba(46,51,72,0.30)
- **Z-index:** 40
- **Overflow-y:** auto
- **Transition:** transform 300ms ease
- **Default:** transform translateX(100%) — hidden off-screen right
- **Open:** transform translateX(0) — slides into view

**Collapsed state (default) — Persistent edge handle:**
- A small vertical handle tab visible on the right edge of the viewport:
  - Position: fixed, right 0, top 50%, transform translateY(-50%), z-index 42
  - Size: 36px wide × 80px tall
  - Border-radius: 8px 0 0 8px (rounded left side only, flush with right edge)
  - Background: #1A1F2E, border 1px solid #2E3348 (no right border)
  - Contains: material `psychology` icon (20px, #00E5A0) centered vertically
  - Below icon: text "AI" rotated 90deg, 8px, #00E5A0, weight 700
  - On hover: background #242938, icon glows (box-shadow 0 0 8px rgba(0,229,160,0.3))
  - Clicking: opens the panel

**Expanded state:**
- Panel slides in from right (transform: translateX(0), transition 300ms ease)
- Handle tab hides (or stays as part of panel edge)
- Close button in panel header collapses it back

**Panel Header:**
- Background: #1A1F2E, padding 12px, border-bottom
- Left: material `psychology` (filled variant, 20px, #00E5A0) + title (`id="panel-title"`: "AI Insights: RELIANCE", 14px bold uppercase)
- Right: Close button (material `close`, #94A3B8 hover white)

**Panel Content** (`id="panel-content"`, padding 16px):

When loading: centered spinner (24px, accent border)

When loaded, 4 sections — **each section individually collapsible:**
- Section headers are clickable
- Chevron icon on the right: material `expand_more` (expanded) / `expand_less` (collapsed)
- Content below header smoothly collapses/expands (max-height transition 200ms)
- Default: all sections expanded on first open
- User's collapse state persists while panel stays open

**Section 1: Outlook Card**
- Border: 1px solid rgba(0,229,160,0.20), border-radius 12px
- Background: rgba(46,51,72,0.20), padding 16px, margin-bottom 16px
- Row 1 (flex, justify-between):
  - Outlook badge: "BULLISH" / "BEARISH" / "NEUTRAL" / "CAUTIOUS"
    - Bullish: bg rgba(0,229,160,0.20), text #00E5A0
    - Bearish: bg rgba(255,107,107,0.20), text #FF6B6B
    - Neutral/Cautious: bg rgba(148,163,184,0.20), text #94A3B8
    - 10px, weight 700, uppercase, padding 4px 8px, rounded-full
  - Confidence: "Confidence: **High**" — 12px, #94A3B8, bold part in #00E5A0
- Row 2: Summary paragraph — 14px, line-height 1.6, margin-bottom 12px
- Row 3 (border-top, padding-top 12px):
  - Label: "ACTION" — 10px, #94A3B8, uppercase
  - Value: e.g., "Strong candidate for swing entry" — 14px, bold, #00E5A0

**Section 2: Strengths & Risks Grid**
- 2-column grid, gap 12px, margin-bottom 16px
- **Left card (Strengths):** background #1A1F2E, border-radius 8px, padding 12px
  - Header: material `verified` (16px, #00E5A0) + "STRENGTHS (5)" — 10px, weight 700, #00E5A0
  - List: each item "+" prefixed, 10px, #94A3B8, spacing 6px
- **Right card (Risks):** same structure
  - Header: material `warning` (16px, #FF6B6B) + "RISKS (2)" — 10px, weight 700, #FF6B6B
  - List: each item "-" prefixed

**Section 3: Indicator Analysis**
- Header: "INDICATOR ANALYSIS" — 10px, weight 700, #94A3B8, uppercase, letter-spacing 0.1em
- Cards list (gap 8px):
  - Each card: background #1A1F2E, border-radius 8px, padding 12px
  - Left border: 2px solid, color based on signal:
    - bullish: #00E5A0
    - bearish: #FF6B6B
    - neutral: #64748B
  - Indicator name: 12px, bold
  - Interpretation: 10px, #94A3B8, line-height 1.5

**Section 4: Filter Inspector**
- Header: "FILTER INSPECTOR" — same section header style, margin-top 16px
- Compact rows (gap 4px):
  - Each row: flex, justify-between, items-center, padding 6px 8px, border-radius 4px, hover background rgba(46,51,72,0.20)
  - Filter name: 10px, width 128px, truncate overflow
  - Status badge: 9px, weight 700, padding 2px 6px, border-radius 4px
    - PASS: background rgba(0,229,160,0.15), text #00E5A0
    - FAIL: background rgba(255,107,107,0.15), text #FF6B6B
    - BORDERLINE: background rgba(255,184,0,0.15), text #FFB800
    - SKIPPED: background rgba(148,163,184,0.15), text #94A3B8
  - Actual value: 10px, #94A3B8, width 96px, text-right, truncate

---

## TAB 2: CONFIGURATION (`id="tab-config"`)

**Container:** margin-top 56px, padding 24px, height calc(100vh - 56px), overflow-y auto

### Header
- Title: "Filter Configuration" — 24px, weight 700
- Subtitle: "Fine-tune your screening parameters." — 14px, #94A3B8, margin-bottom 24px

### Config Grid (`id="config-grid"`)
- **Layout:** grid, 1 column (mobile), 2 columns (md), 3 columns (xl), gap 16px

#### Per-Filter Card (one for each of the 44 filters)
- Background: #1A1F2E, padding 16px, border-radius 12px, border 1px solid rgba(46,51,72,0.10)
- **Hover:** translateY(-2px), box-shadow 0 8px 24px rgba(0,0,0,0.3), border-color transitions to rgba(0,229,160,0.15)
- **Header row** (flex, justify-between, items-center, margin-bottom 12px):
  - Filter name: 14px, weight 700, capitalize (underscores → spaces)
  - Status: "ON" (text #00E5A0) or "OFF" (text #64748B) — 10px
- **Parameter rows** (for each param except 'enabled'):
  - Flex, justify-between, items-center, padding 4px vertical
  - Label: 10px, #94A3B8
  - Input: background #242938, no border, border-radius 4px, 12px text #00E5A0, width 80px, text-right, padding 4px 8px

### Fixed Bottom Preset Bar
- **Position:** fixed, bottom 0, left 0, right 0, height 64px
- **Background:** rgba(10,14,26,0.90) with backdrop-blur-xl
- **Border-top:** 1px solid rgba(46,51,72,0.20)
- **Padding:** 0 24px
- **Layout:** flex, items-center, justify-between

**Left section:**
- Text input (`id="preset-name"`): background #111827, no border, border-radius 8px, 14px, padding 8px 12px, width 192px, placeholder "Preset name..."
- "Save Preset" button: background #00E5A0, text #00382b, padding 8px 16px, border-radius 8px, 12px weight 700

**Right section:**
- Preset dropdown (`id="preset-select"`): background #242938, no border, border-radius 8px, 12px, padding 8px 12px. Default: "Load Preset..."
  - onchange: loads and applies selected preset config
- Reset button: text #94A3B8, hover white, 12px, flex items-center gap 4px
  - Material icon `restart_alt` (16px) + text "Reset"

---

## TAB 3: INDICATORS (`id="tab-indicators"`)

**Container:** margin-top 56px, padding 24px, height calc(100vh - 56px), overflow-y auto

### Header
- Title: "Available Indicators" — 24px, weight 700
- Count text (`id="ind-count"`): "25 indicators available" — 14px, #94A3B8, margin-bottom 24px

### Indicators Grid (`id="indicators-grid"`)
- **Layout:** grid, 1/2/3/4 columns (responsive), gap 16px

#### Per-Indicator Card
- Background: #1A1F2E, border-radius 12px, padding 16px
- **If highlighted** (supertrend, vwap_bands, vortex): border 1px solid #00E5A0, box-shadow 0 0 12px rgba(0,229,160,0.20) — "glow-green" class
- **Hover:** translateY(-2px), box-shadow 0 8px 24px rgba(0,0,0,0.3), border-color transitions to rgba(0,229,160,0.15), transition 200ms

**Card contents:**
1. **Header** (flex, justify-between):
   - Type label: 10px, #94A3B8, uppercase (e.g., "Oscillator", "Trend")
   - Name: 14px, weight 700
2. **Description:** 10px, #94A3B8, line-clamp 2 (max 2 lines with ellipsis)
3. **Parameter pills** (flex wrap, gap 4px, margin-bottom 12px):
   - Each: background #111827, padding 2px 6px, border-radius 4px, 9px
   - Format: "param_name: **value**" — label in #94A3B8, value in #00E5A0 bold
4. **Tier badge:**
   - "Most Precise": 10px weight 700, text #F59E0B, background rgba(245,158,11,0.10), padding 2px 6px, rounded-full
   - "Hidden Gem": same but text #8B5CF6, background rgba(139,92,246,0.10)
   - "Standard": 10px italic, text #64748B, no background

---

## TAB 4: WATCHLIST (`id="tab-watchlist"`)

**Container:** margin-top 56px, padding 16px, height calc(100vh - 56px), overflow-y auto

### 4.1 Watchlist Header
**Layout:** flex, justify-between, items-center, margin-bottom 16px

**Left side (flex, gap 12px, items-center):**
- Title: "Watchlist" — 24px, weight 700
- Count badge (`id="wl-count"`): "4" — 12px, weight 700, background rgba(0,229,160,0.20), text #00E5A0, padding 2px 8px, rounded-full
- Triggered count badge (`id="wl-triggered-count"`): hidden by default
  - When visible: e.g., "2 triggered" — 12px, weight 700, background rgba(0,229,160,0.30), text #00E5A0, animate-pulse

**Right side:**
- Check Alerts button (`id="wl-check-btn"`):
  - Background: #00E5A0, text #00382b, padding 8px 16px, border-radius 12px, 14px weight 700
  - Icon: material `notifications_active` (16px)
  - **During check:** disabled, icon changes to `sync` with animate-spin, text "Checking..."
  - **After check:** re-enabled, original icon + "Check Alerts" text

### 4.2 Add Symbol Bar
**Layout:** flex, gap 8px, margin-bottom 16px

- **Input** (`id="wl-add-input"`):
  - Flex-grow
  - Styling: same as symbol input on screener
  - Placeholder: "Add symbol: RELIANCE, TCS, HDFCBANK..."
  - **onkeydown:** if Enter key pressed, calls addToWatchlist()
  - Supports comma-separated symbols

- **Add Button:**
  - Background: #0566D9, text white, padding 10px 16px, border-radius 12px, 14px weight 700
  - Icon: material `add` (16px) + text "Add"

### 4.3 Watchlist Table
**Card:** background #111827, border-radius 12px, overflow hidden

**Table headers** (background #1A1F2E):

| Column | Align | Width |
|--------|-------|-------|
| Symbol | left | auto |
| Price | right | auto |
| Score | right | auto |
| Alerts | center | auto |
| Status | center | auto |
| Actions | center | auto |

**Empty state (when empty):**
- Material `bookmark_border` (48px, #2E3348) + "Your watchlist is empty" (16px, #475569) + "Add stocks above or bookmark results from the Screener" (12px, #2E3348) + "Go to Screener →" link in #00E5A0

**Row template for each watchlist item:**
```
Row: hover bg rgba(0,229,160,0.03), translateX(2px), 2px left-border accent fades in
border-bottom 1px solid rgba(46,51,72,0.10)
If this stock has triggered alerts: additional bg rgba(0,229,160,0.05) tint
Triggered rows sorted first, then by score.

Column 1 (Symbol):
  Line 1: symbol name, font-bold, cursor pointer, hover text #00E5A0
    onClick: switches to Screener tab, opens chart for this symbol (100ms delay)
  Line 2: date added, 9px, text #475569, formatted as locale date string

Column 2 (Price): "₹2472.68" — right-aligned, font-mono
  Shows "--" if no price data yet

Column 3 (Score): right-aligned, font-bold
  Color coding: score ≥ 60 → #00E5A0, score ≥ 40 → #F59E0B (amber), score < 40 → #94A3B8
  Shows "--" if not yet checked

Column 4 (Alerts): count badge
  e.g., "1" — 10px, background #2E3348, padding 2px 6px, border-radius 4px

Column 5 (Status):
  If alerts_triggered > 0: "BREAKOUT TRIGGERED" badge
    10px, weight 700, background rgba(0,229,160,0.25), text #00E5A0
    Border: 1px solid rgba(0,229,160,0.50)
    CSS animation: glow-pulse 1.5s ease-in-out infinite
    (glow-pulse: box-shadow oscillates between 8px and 20px spread of rgba(0,229,160))
  Else if has alerts (count > 0): "WATCHING" badge
    10px, background rgba(148,163,184,0.15), text #94A3B8
  Else: "No alerts" — 10px, text #475569

Column 6 (Actions): flex, gap 4px, justify-center
  Add Alert: material add_alert (16px), #94A3B8, hover #00E5A0, title "Add alert"
    onClick: opens alert modal for this symbol
  Chart: material candlestick_chart (16px), #94A3B8, hover #00E5A0, title "Chart"
    onClick: switches to Screener tab, opens chart
  Delete: material delete (16px), #94A3B8, hover #FF6B6B, title "Remove"
    onClick: removes stock from watchlist, reloads
```

### 4.4 Expandable Alert Detail Rows

After each stock row, if that stock has alert results (after checking), an additional row appears:
- Background: rgba(26,31,46,0.50)
- Spans all 6 columns
- Padding: 8px 16px
- Contains a vertical stack of individual alert results (gap 6px)

**Each alert result row:**
- Layout: flex, items-center, gap 8px, font-size 10px
- **Type icon** (12px, #64748B):
  - indicator alerts: material `analytics`
  - price alerts: material `monetization_on`
  - preset alerts: material `tune`
- **Status badge:**
  - TRIGGERED: background rgba(0,229,160,0.20), text #00E5A0, border 1px solid rgba(0,229,160,0.40), 9px weight 700, padding 2px 6px, rounded-full, glow-pulse animation 2s
  - WAITING: background rgba(148,163,184,0.15), text #94A3B8, 9px, padding 2px 6px, rounded-full
- **Message:** e.g., "RSI = 39.84" — 10px, #94A3B8
- **Details:** e.g., "crosses_above 50.0" — 10px, #64748B
- **Delete button** (margin-left auto): material `close` (12px), #475569, hover #FF6B6B
  - onClick: removes this specific alert, reloads watchlist

### 4.5 Alert Setup Modal (`id="wl-alert-modal"`)

- **Overlay:** fixed inset 0, background rgba(0,0,0,0.60), z-index 50, flex center
- **Default:** display none
- **Open:** display flex

**Modal box:**
- Background: #111827, border-radius 16px, padding 24px, width 420px
- Border: 1px solid rgba(46,51,72,0.30)

**Header** (flex, justify-between, margin-bottom 16px):
- Title (`id="wl-alert-modal-title"`): "ADD ALERT: RELIANCE" — 14px, weight 700, uppercase
- Close button: material `close`, #94A3B8, hover white

**Form fields** (vertical stack, gap 12px):

#### Alert Type Selector
- Label: "ALERT TYPE" — 10px, #94A3B8, uppercase
- Dropdown (`id="wl-alert-type"`): full width, background #242938, no border, border-radius 8px, 12px, padding 8px 12px
  - Options: "Indicator Condition", "Price Level", "Preset Match"
  - onChange: shows/hides the appropriate field group below

#### Indicator Condition Fields (`id="wl-alert-indicator-fields"`)
**Visible when type = "indicator":**
- Indicator dropdown (`id="wl-alert-indicator"`): same select styling
  - Options: RSI, EMA, MACD, Supertrend, ADX, OBV, CMF, Vortex, ROC, Fisher Transform, Stochastic RSI, Williams %R
- Condition dropdown (`id="wl-alert-condition"`):
  - Options: Crosses Above, Crosses Below, Above, Below, Passes Filter
- Value input (`id="wl-alert-value"`): number type, placeholder "e.g., 50"

#### Price Level Fields (`id="wl-alert-price-fields"`)
**Visible when type = "price" (hidden by default):**
- Condition dropdown (`id="wl-alert-price-condition"`):
  - Options: Price Above, Price Below
- Price input (`id="wl-alert-price-value"`): number type, placeholder "e.g., 1500", label shows "TARGET PRICE (₹)"

#### Preset Match Fields (`id="wl-alert-preset-fields"`)
**Visible when type = "preset" (hidden by default):**
- Preset dropdown (`id="wl-alert-preset-select"`): populated from saved presets
- Helper text: "Stock will be screened with this preset's filters. Triggers when it passes." — 9px, #64748B

**Action buttons** (flex, gap 8px, margin-top 20px):
- "Add Alert" button: flex-grow, background #00E5A0, text #00382b, padding 8px, border-radius 8px, 12px weight 700
- "Cancel" button: padding 8px 16px, background #242938, border-radius 8px, 12px, text #94A3B8

---

## YOINTELL CHAT AGENT (Floating Panel)

### Chat FAB (Floating Action Button)
- Position: fixed, bottom 24px, right 24px, z-index 45
- Size: 52px × 52px, border-radius 50%
- Background: linear-gradient(135deg, #00E5A0, #00B4D8)
- Icon: material `smart_toy` (24px, #0A0E1A)
- Box-shadow: 0 4px 16px rgba(0,229,160,0.30)
- Hover: scale(1.1), shadow → 0 8px 24px rgba(0,229,160,0.40), icon rotates 15deg
- **When chat open:** icon changes to `close`, background becomes #2E3348
- **Notification dot:** 8px red circle (#FF6B6B) pulsing, on top-right of FAB, hidden when chat is open

### Chat Panel
- Position: fixed, bottom 88px, right 24px, z-index 44
- Size: 380px × 520px
- Background: #111827, border-radius 16px, border 1px solid #2E3348
- Box-shadow: 0 12px 40px rgba(0,0,0,0.5)
- Default: hidden (opacity 0, pointer-events none)
- Open animation: opacity 0→1 + translateY(20px→0) over 250ms ease
- Close animation: reverse

**Chat Header (52px):**
- Background: #1A1F2E, border-radius 16px 16px 0 0
- Padding: 0 16px, flex, items-center, gap 10px
- Bot avatar: 28px circle, gradient background, `smart_toy` icon (14px, #0A0E1A)
- Title: "Yointell Assistant" — 13px, weight 700, #E8ECF4
- Subtitle: "AI-powered" — 9px, #00E5A0, weight 500
- Right: minimize button (material `minimize`, 16px, #94A3B8)

**Chat Message Area:**
- Flex-grow, overflow-y auto, padding 16px
- Background: #0A0E1A (slightly darker for depth)
- Custom scrollbar: 4px thin

**User messages (right-aligned):**
- Max-width: 80%, margin-left auto
- Background: rgba(0,229,160,0.08), border 1px solid rgba(0,229,160,0.12)
- Border-radius: 12px 12px 2px 12px
- Padding: 10px 14px, font 12px, color #E8ECF4
- Margin-bottom 12px

**Assistant messages (left-aligned):**
- Max-width: 85%
- Background: #1A1F2E, border 1px solid #2E3348
- Border-radius: 12px 12px 12px 2px
- Padding: 10px 14px, font 12px, color #E8ECF4
- Supports markdown bold (**text**), bullet lists, inline code
- **Action chips** (inline within message text):
  - Pill: background rgba(0,229,160,0.12), text #00E5A0, 10px weight 700, padding 2px 8px, border-radius 10px
  - Brief glow animation on appearance (0.5s)
  - e.g., "Applied preset: [momentum]" — [momentum] is the glowing chip

**Typing indicator:**
- Three 6px #00E5A0 dots, bouncing with staggered 150ms delay (bounce-dot keyframes)
- Visible while waiting for backend response

**Welcome message (shown on first open):**
- "Hey! I'm your Yointell assistant. I can:
  - Toggle filters — *"enable only RSI and Supertrend"*
  - Screen stocks — *"screen Nifty 200"*
  - Create strategies — *"create momentum strategy"*
  - Manage watchlist — *"add SBIN to watchlist"*
  - Explain indicators — *"what is RSI?"*"

**Chat Input Bar (56px):**
- Background: #111827, border-top 1px solid #2E3348, border-radius 0 0 16px 16px
- Padding: 8px 12px, flex, items-center, gap 8px
- Input: flex-grow, background #0A0E1A, border 1px solid #2E3348, border-radius 20px, padding 8px 16px, 13px, color #E8ECF4
  - Placeholder: "Ask anything..." in #475569
  - Focus: border-color #00E5A0
  - Enter key: sends message
- Send button: 36px circle, background #00E5A0 (when input has text) / #2E3348 (empty)
  - Icon: material `send` (16px), color #0A0E1A (active) / #475569 (disabled)
  - Disabled when input empty
  - Hover (active): scale(1.1)

---

## VISUAL QUALITY CHECKLIST (must-haves for professional feel)

1. All number columns use `font-feature-settings: 'tnum' 1` for perfect decimal alignment
2. All prices show ₹ symbol (Unicode \u20b9) with 2 decimal places
3. Score color gradient: ≥60 bright green (#00E5A0), 40-59 amber (#F59E0B), <40 gray (#94A3B8)
4. Table rows have barely-visible alternating stripe (rgba(255,255,255,0.02) on even rows)
5. Empty states always have centered, helpful gray text with relevant material icons
6. Loading states use AI-themed triple ring animation (not plain spinners)
7. All interactive elements have 200ms transition with tactile micro-feedback (scale snap-back)
8. Custom scrollbars: 6px wide, rounded, thumb #2E3348, track transparent
9. Cards have very subtle top-edge highlight (1px linear-gradient from rgba(255,255,255,0.05) to transparent)
10. Badges use consistent rounded-full pill shape with 10px text
11. Filter chips have inline editable param values (32px width, right-aligned)
12. No element uses default browser styling — everything is custom dark theme
13. Material Symbols loaded from Google Fonts CDN
14. Inter font loaded from Google Fonts CDN
15. Tailwind CSS loaded from CDN (with forms and container-queries plugins)
16. TradingView Lightweight Charts 4.1.0 loaded from unpkg CDN
17. body has overflow-hidden to prevent double scrollbars
18. The page title should be "Yointell - NSE Swing Screener"

## IMPORTANT RULES

1. **Exactly 4 tabs only:** Screener, Configuration, Indicators, Watchlist. NO "Create Script", "Strategy Builder", "Script Editor", or any 5th tab. Strategy/script creation is done through the chat agent.
2. **All 44 filter chips must be present** on the Screener tab with enable/disable toggles.
3. **All 3 scope options** (Nifty 200, Nifty 500, All NSE) must be present as pills in the search bar.
4. **Search bar placed above stage tables** — not buried inside any action bar or elsewhere.
5. **Candlestick chart** uses TradingView Lightweight Charts 4.1.0 (placeholder in design tool is fine, real library used in production).
6. **No features removed** — everything listed above must exist in the final design.
7. **Page title:** "Yointell - NSE Swing Screener"
8. **CDNs:** Tailwind CSS (forms + container-queries plugins), Inter font, Material Symbols, Lightweight Charts 4.1.0
9. body: overflow-hidden to prevent double scrollbars
10. All prices use ₹ symbol. Scores color-coded (≥60 green, 40-59 amber, <40 gray). Tabular numerals throughout.

## OVERALL AESTHETIC

Bloomberg Terminal redesigned by the Linear.app + Vercel design team. Information-dense but never cluttered. Dark but warm (navy, not black). Data-rich but scannable at a glance. Every element communicates "institutional-grade professional tool" while remaining approachable for retail Indian traders. Koyfin's data density + TradingView's charting polish + Stripe's typographic precision. Every interaction feels deliberate, snappy, and rewarding — psychologically easy, the eye knows exactly where to go at every step.
