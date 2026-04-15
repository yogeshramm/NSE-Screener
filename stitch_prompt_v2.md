# YOINTELL v2 — Additions & Corrections to Existing Design

Apply ALL of the following changes to the existing design. **Do NOT remove any existing features.** Everything currently in the design MUST stay exactly as it is. These are ADDITIONS, CORRECTIONS, and POLISH only.

**UX Psychology Principles Applied Throughout:**
- Reduce cognitive load: group related controls, use progressive disclosure (collapsible sections), show only what matters at each step
- Fitt's Law: primary actions (Screen, Add, Check Alerts) are large, high-contrast, easy to target
- Recognition over recall: status badges, color-coded scores, visual icons — user never has to remember what numbers mean
- Feedback loops: every click produces immediate visual feedback (glow, animation, state change)
- Gestalt proximity: related items grouped with consistent spacing; unrelated sections separated by clear dividers
- Information scent: users can always tell where to go next via visual hierarchy and accent colors guiding the eye

---

## CORRECTION 1: YOINTELL LOGO — AI-NATIVE ANIMATED IDENTITY

Replace the plain logo text "YOINTELL" in the nav bar with a premium animated treatment:

**Logo container (top-left of nav, flex column):**
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
  @keyframes gradient-shift {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
  }
  ```
- **Tagline below logo:** "Predictive Stock Intelligence" — 8px, weight 500, letter-spacing 0.12em, uppercase, color #475569
- **On first page load:** Logo text types out letter-by-letter (typewriter effect over 1.2 seconds), then gradient animation begins
- **On hover:** brightness 1.2, subtle scale(1.02), 300ms transition

---

## CORRECTION 2: SEARCH BAR — PROMINENT PLACEMENT ABOVE STAGE TABLES

The stock search must be a prominent, dedicated search section placed BETWEEN the action bar and the result tables. Not buried inside the action bar.

**Search Section (full-width glassmorphic bar, below filter panel + action controls, above stage tables):**
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
   - Background: #60A5FA, color white, same pill shape
   - Icon: material `bolt` (16px)
   - Hover: scale(1.05)

---

## CORRECTION 3: AI INSIGHTS PANEL — COLLAPSIBLE WITH SIDE HANDLE

The existing AI Insights side panel (400px, slides from right) must become a collapsible panel with a persistent edge handle:

**Collapsed state (default):**
- Panel is hidden (transform: translateX(100%))
- A small vertical handle tab is visible on the right edge of the viewport:
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
- Close button (×) in panel header collapses it back

**Inside the panel — each section is individually collapsible:**
- Section headers (Outlook, Strengths & Risks, Indicator Analysis, Filter Inspector) are clickable
- Chevron icon on the right: material `expand_more` (expanded) / `expand_less` (collapsed)
- Content below header smoothly collapses/expands (max-height transition 200ms)
- Default: all sections expanded on first open
- User's collapse state persists while panel stays open

---

## CORRECTION 4: CHART PANEL — KITE-STYLE INDICATOR MANAGEMENT

The chart panel (right side, opens when stock clicked) must have Zerodha Kite-style indicator controls:

**Chart Toolbar (inside chart header, between title and close button):**
- Layout: flex, gap 4px, items-center

1. **"Studies" / "Indicators" button:**
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

3. **Indicator Picker Dropdown** (opens below the Studies button):
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

---

## CORRECTION 5: HOVER DYNAMISM & MICRO-INTERACTIONS (ENTIRE UI)

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
- Active: 2px bottom border with gradient matching logo gradient

**Download ring:** hover scale(1.1) with subtle glow
**Sync button:** hover icon rotates 180deg, background brightens
**Avatar:** hover ring glow around it

---

## CORRECTION 6: AI-THEMED LOADING ANIMATIONS

Replace all plain spinners with on-brand AI-themed animations:

**Main screening loader (when Screen button clicked):**
- Three concentric rings animation (centered):
  - Outer ring: 44px, 2px border rgba(0,229,160,0.12), rotating clockwise 3s
  - Middle ring: 30px, 2px border rgba(0,229,160,0.25), rotating counter-clockwise 2s
  - Inner ring: 18px, 2px border #00E5A0, rotating clockwise 1.5s
  - Center dot: 4px solid #00E5A0, pulsing opacity
- Below rings: text with typewriter animation — "Analyzing stocks..." characters appear one by one
- Then: progress text "Screening 127 / 500 stocks..." updates live during scan
- Below that: "Stop Screening" red button (same as current)

**Chat agent thinking indicator:**
- Three 6px dots in #00E5A0, bouncing with staggered 150ms delay:
  ```css
  @keyframes bounce-dot { 0%,80%,100% { transform: translateY(0) } 40% { transform: translateY(-8px) } }
  ```

**Data sync progress ring:**
- When syncing: ring stroke animates with sweeping dash effect
- Percentage text pulses subtly

**Page initial load:**
- "YOINTELL" types out letter-by-letter (typewriter, 1.2s total)
- Then gradient animation begins
- Brief fade-in of all content (300ms) after logo completes

---

## ADDITION 1: LOGIN / REGISTER PAGE

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

## ADDITION 2: USER PROFILE & LOGOUT IN NAV BAR

Add to the RIGHT side of the nav bar (after the sync button cluster):

**Profile avatar button:**
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

**Dropdown contents:**
- **User info:** display_name (14px, weight 600, #E8ECF4) + username below (11px, #64748B)
- **Divider:** 1px solid #2E3348, margin 8px 0
- **Logout row:** flex, items-center, gap 8px, padding 8px 12px, border-radius 8px, cursor pointer
  - Icon: material `logout` (16px, #FF6B6B)
  - Text: "Logout" — 13px, #FF6B6B
  - Hover: background rgba(255,107,107,0.08)
- **Click outside** dropdown: closes it

---

## ADDITION 3: YOINTELL CHAT AGENT (FLOATING PANEL)

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
- Three 6px #00E5A0 dots, bouncing with staggered 150ms delay
- Visible while waiting for backend response

**Welcome message (shown on first open):**
- "Hey! I'm your Yointell assistant. I can:\n• Toggle filters — *\"enable only RSI and Supertrend\"*\n• Screen stocks — *\"screen Nifty 200\"*\n• Create strategies — *\"create momentum strategy\"*\n• Manage watchlist — *\"add SBIN to watchlist\"*\n• Explain indicators — *\"what is RSI?\"*"

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

## ADDITION 4: REMOVE "CREATE SCRIPT" PAGE

If a "Create Script", "Strategy Builder", "Script Editor", or any 5th tab exists in the current design — **DELETE IT COMPLETELY**.

The application has exactly **4 tabs only**: Screener, Configuration, Indicators, Watchlist. No other tabs or pages. Strategy/script creation is done through the chat agent.

---

## ADDITION 5: ENHANCED EMPTY STATES

**Stage 1 table (before any screening):**
- Centered content: material `radar` (48px, #2E3348) + "Run a screen to discover swing candidates" (14px, #475569) + "Select filters and click Screen, or search specific stocks" (11px, #2E3348)

**Stage 2 table (before any screening):**
- Material `trending_up` (48px, #2E3348) + "Breakout candidates appear after Stage 1" (14px, #475569)

**Watchlist (when empty):**
- Material `bookmark_border` (48px, #2E3348) + "Your watchlist is empty" (16px, #475569) + "Add stocks above or bookmark results from the Screener" (12px, #2E3348) + "Go to Screener →" link in #00E5A0

---

## ADDITION 6: DATA STATUS POLISH

The download ring + status cluster in the nav should reflect states clearly:
- **Synced:** green pulsing dot (4px) next to "Synced" text, ring shows ✓
- **Downloading:** animated ring sweep, percentage text, "Downloading..." with animated ellipsis
- **Offline:** red dot (4px) + "Server offline" in #FF6B6B + tiny text "Start server" in #475569

---

## EXPLICIT PRESERVATION LIST — DO NOT REMOVE

Verify all of these exist in the final design:

### Screener Tab
- [x] Collapsible filter panel (120px collapsed, 400px expanded, smooth transition)
- [x] 3 category sections: Technical (19 filters), Fundamental (11), Breakout & Risk (14)
- [x] Each filter chip: checkbox + uppercase label + inline editable parameter value
- [x] 3 highlighted filters with ⭐ star + glow: Supertrend, VWAP Bands, Vortex
- [x] Filter count badge (e.g., "32/44")
- [x] Enable All / Disable All buttons
- [x] Preset dropdown on filter bar + active preset dismissable badge + quick-save icon
- [x] Search bar with Nifty 200 / Nifty 500 / All NSE scope pills + Screen button + Run button
- [x] Loading state with AI spinner + Stop Screening button
- [x] Stage 1: Swing Base table (rank, stock+sector, price, PE, RSI, ROE%, score, status badge, bookmark icon)
- [x] Stage 2: Breakout table (rank, stock, price, SL in red, target in green, R:R, score, status, bookmark)
- [x] Kite-style split: tables shrink to 320px, chart fills remaining
- [x] Candlestick chart with indicator overlay management (add/remove like Zerodha Kite)
- [x] Chart overlays: EMA 50 (yellow), EMA 200 (blue), Supertrend (teal)
- [x] RSI sub-panel (80px, purple line, 30/70 dashed levels)
- [x] Volume sub-panel (60px, green/red histogram)
- [x] Cross-chart sync (crosshair syncs main chart ↔ RSI ↔ Volume)
- [x] AI Insights collapsible side panel (400px) with edge handle
- [x] Bookmark buttons on result rows to add to watchlist

### Configuration Tab
- [x] Grid of filter parameter cards (responsive 1/2/3 columns)
- [x] Each card: filter name + ON/OFF badge + editable param rows
- [x] Fixed bottom preset bar (name input + Save | Load dropdown + Reset)

### Indicators Tab
- [x] Grid of 25 indicator cards (responsive 1-4 columns)
- [x] Each card: type, name, description, param pills, tier badge
- [x] Tier badges: Most Precise (gold), Hidden Gem (purple), Standard (gray)
- [x] Highlighted cards (3) have glow border

### Watchlist Tab
- [x] Header: title + count badge + triggered count badge + Check Alerts button
- [x] Add input (Enter key support) + Add button
- [x] Table: Symbol+date, Price (₹ monospace), Score (color-coded), Alerts count, Status, Actions
- [x] BREAKOUT TRIGGERED badge (glow pulse animation)
- [x] WATCHING badge (gray)
- [x] No alerts text (dim)
- [x] Expandable alert detail rows (type icon + TRIGGERED/WAITING badge + message + delete)
- [x] Alert modal: 3 types (indicator condition, price level, preset match)
- [x] Action buttons: add_alert, chart, delete per row
- [x] Triggered rows sorted first, subtle green tint background

### Floating Elements
- [x] Chat FAB (bottom-right, 52px circle)
- [x] Chat panel (380px × 520px)
- [x] AI Insights side handle (right edge)
- [x] Auth overlay (full page, z-100)
- [x] User profile avatar + logout dropdown (nav right)

### Global
- [x] 56px nav bar with glass effect
- [x] 4 tab buttons (Screener, Configuration, Indicators, Watchlist)
- [x] Download progress ring (36px SVG, clickable)
- [x] Data status labels (stocks cached, data date, stock+day count)
- [x] Sync button with dynamic text
- [x] Dark theme throughout (#0A0E1A base, NOT pure black)
- [x] Inter font, tabular numerals
- [x] 6px thin custom scrollbars
- [x] All transitions 200ms ease
- [x] Glassmorphic card backgrounds
