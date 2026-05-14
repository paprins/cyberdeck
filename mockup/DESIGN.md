# Design System Document: Survivalist Utility & Offline Resilience

## 1. Overview & Creative North Star: "The Analog Digitalist"
This design system rejects the ephemeral softness of modern web design in favor of a "Survivalist" aesthetic—rugged, indestructible, and high-utility. The **Creative North Star** is **"The Analog Digitalist"**: a UI that feels like a military-grade field computer or an offline black-box recorder.

To move beyond a "standard" dark mode, we utilize **Intentional Asymmetry** and **Rigid Brutalism**. By removing all rounded corners (`0px` radius) and relying on sharp, geometric intersections, we communicate a sense of structural integrity. The layout should feel like it was machined from a single block of carbon fiber, prioritizing data density and immediate legibility over "decorative" whitespace.

---

## 2. Colors: High-Contrast Tactical Depth
The palette is built on a foundation of absolute blacks and bruised purples, pierced by high-visibility safety accents.

### The "No-Line" Rule
**Explicit Instruction:** Do not use 1px solid borders to section content. Boundaries must be defined solely by background shifts.
- To separate a sidebar from a main feed, transition from `surface-container-lowest` (#0e0e0e) to `surface` (#131313). 
- If a section requires emphasis, use a background shift, never an outline.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical plates.
- **Base Layer:** `surface` (#131313) for the primary application background.
- **Inset Content:** `surface-container-lowest` (#0e0e0e) for deep, recessed archive lists.
- **Elevated Controls:** `surface-container-highest` (#353535) for active utility panels.
- **Nesting Logic:** Always move "inward" or "upward" by one tier. A card on the `surface` should be `surface-container-low`, and an input field inside that card should be `surface-container-high`.

### The "Glass & Gradient" Rule
Standard survival gear isn't just flat; it has texture.
- Use **Glassmorphism** for floating overlays (e.g., critical alerts) using `surface-variant` (#353535) at 60% opacity with a `20px` backdrop-blur. 
- **Signature Gradients:** For primary actions, use a subtle vertical gradient from `primary-container` (#ff6b00) to `primary` (#ffb693). This adds "soul" and mimics the glow of a physical LED indicator.

---

## 3. Typography: Command & Control
We pair the technical precision of monospaced accents with the high-speed legibility of a clean sans-serif.

- **Display & Headlines (Space Grotesk):** These are your "read-outs." Use `display-lg` for terminal-style headers. The geometric nature of Space Grotesk provides the "technical" soul of the brand.
- **Body & Titles (Inter):** Inter is the workhorse. Use `body-md` for all instruction-based content. Its high x-height ensures readability in low-light, high-stress offline scenarios.
- **Labels (Space Grotesk):** Use `label-sm` for metadata (file sizes, timestamps, coordinates). This creates a visual distinction between "Human Content" and "System Data."

---

## 4. Elevation & Depth: Tonal Layering
In a survivalist system, shadows are rarely used because light sources are scarce. Hierarchy is achieved through **Tonal Stacking**.

- **The Layering Principle:** To "lift" an element, simply step up the surface tier. A floating modal should use `surface-bright` (#393939) against the `surface-dim` (#131313) background.
- **Ambient Shadows:** Only use shadows for high-priority floating elements (like a FAB). Use the `on-surface` color (#e2e2e2) at 4% opacity with a massive `48px` blur. It should feel like a faint glow rather than a drop shadow.
- **The "Ghost Border" Fallback:** If a distinction is critical for accessibility, use `outline-variant` (#5a4136) at **15% opacity**. This creates a "machined groove" look rather than a drawn line.

---

## 5. Components: Machined Functionality

### Buttons (Indestructible Rectangles)
- **Primary:** `primary-container` (#ff6b00) background, `on-primary-container` (#572000) text. 0px radius. Massive uppercase labels using `label-md`.
- **Secondary:** `surface-container-highest` background with a `Ghost Border`.
- **State Transition:** On hover/active, shift the background color 10% brighter. No "soft" transitions; use `50ms` or `0ms` for an instant, tactile response.

### Input Fields & Controls
- **Text Inputs:** Use `surface-container-lowest` as the field background. The active state is indicated by a 2px bottom-bar of `primary` (#ffb693), mimicking a terminal cursor.
- **Checkboxes/Radios:** Pure geometric forms. A checked state should be a solid block of `primary-container`. Unchecked is a `Ghost Border` square.
- **Cards & Lists:** **Prohibit dividers.** Use `spacing-4` (0.9rem) or `spacing-6` (1.3rem) of vertical space to separate items. If separation is needed, use alternating background tints (`surface` vs `surface-container-low`).

### Specialized Survivalist Components
- **Data-Strip:** A thin horizontal bar using `secondary-container` to house "Technical Data" like battery life, storage capacity, and encryption status.
- **Status Beacon:** A small pulsing circle using `tertiary-container` (#059eff) to indicate "Scanning" or "Syncing" processes.

---

## 6. Do's and Don'ts

### Do:
- **Use 0px corners everywhere.** The app should look like it could survive a drop from a helicopter.
- **Embrace Monospacing.** Use it for any numerical or system-generated data to evoke a "low-level" technical feel.
- **Lean into Asymmetry.** Align metadata to the right while labels are to the left to create a "tabulated" technical layout.

### Don't:
- **No Rounded Corners.** Even a 2px radius ruins the "Indestructible" intent.
- **No Soft Grays.** Use the purples (`on-secondary-container`) and oranges for depth. Standard #666 grays have no place in this high-contrast world.
- **No Transitions.** Avoid "ease-in-out." Survivalism is about speed and certainty. Use "linear" or "step" animations for a rugged, mechanical feel.

### Accessibility Note:
Ensure all orange `primary` elements maintain a high contrast ratio against the `surface` levels. Use `on-primary-fixed` (#351000) for text on orange backgrounds to ensure maximum legibility during "field use."