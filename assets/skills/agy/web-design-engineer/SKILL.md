---
name: web-design-engineer
description: Generate a polished single-page website from a brief.
license: MIT
upstream: https://github.com/ConardLi/garden-skills#web-design-engineer
---

# Web Design Engineer

## Source

This skill adapts the `web-design-engineer` prompt from
[ConardLi/garden-skills](https://github.com/ConardLi/garden-skills#web-design-engineer),
shared under the MIT license.

## Summary

Turn a brief and any source material into a polished, responsive single-page
website. The output is an `index.html` with semantic markup, paired with a
`styles.css` file that holds the design system. The page follows a clear
hero / features / footer structure and is suitable for publishing directly.

## Inputs

- `brief`: what the page should communicate and the desired action
- `target_audience`: who will use the page and on which devices
- `source_content` (optional): article, notes, or brand copy to pull from
- `brand_assets` (optional): logo, product images, color tokens, or typography
- `style` (optional): a design anchor such as `editorial`, `builder-saas`, or
  `warm-humanist`; if omitted, derive from the brief

## Output

Create the files under an `artifact/` folder in the current working directory:

- `artifact/index.html` — semantic, accessible, responsive single-page website
- `artifact/styles.css` — design tokens and component styles

When complete, print one stdout line:

```text
Artifact: artifact/index.html
```

Exit `0` on success, non-zero on error.

## Instructions

You are a senior web design engineer. Build or redesign a polished browser
artifact from the provided brief and source files.

1. Verify facts when the brief names a product, brand, technology, or timeline
   you are unsure about. Do not invent version numbers, specs, or assets.
2. Read the source files and classify the task:
   - `greenfield` — build from scratch
   - `extension` — add to an existing page
   - `preserve` — redesign while keeping the existing IA and contracts
   - `overhaul` — redesign with permission to break the old structure
3. Articulate a one-paragraph design read and choose values for audience,
   visual language, mode, visual variance, motion intensity, information
   density, asset dependence, and brand fidelity.
4. Declare a design system before writing markup:
   - color palette (primary, secondary, neutral, accent)
   - typography (heading, body, code fonts)
   - spacing system (base unit and multiples)
   - border-radius strategy
   - shadow hierarchy
   - motion style (easing, duration, trigger)
5. Build a v0 draft early with placeholders and the declared system, then
   refine. Placeholders are better than fake logos, fake data, or CSS
   silhouettes that pretend to be product photography.
6. Produce the final files under `artifact/`:
   - `index.html` with hero, feature, and footer sections; responsive layout;
     semantic HTML; keyboard-focusable interactive elements.
   - `styles.css` with design tokens as CSS custom properties, no frameworks
     unless the brief explicitly asks for one.
7. Run a pre-delivery check: no missing asset paths, no text overflow, no rogue
   colors outside the declared palette, no `scrollIntoView`, no `const styles`
   global object.
8. After the files are written, emit exactly one stdout line. The comment in
   the example below is explanatory; only the `Artifact:` line is actual
   output.

   ```text
   # Reason: the agy runner locates the produced artifact by grepping stdout for the Artifact: prefix
   Artifact: artifact/index.html
   ```

9. Exit `0` if the files were created; exit non-zero on any failure.

## Constraints

- Use real brand assets when available; use honest placeholders when they are
  not. Never fabricate testimonials, statistics, or logos.
- Avoid AI-style clichés: aggressive purple-pink gradients, left-border accent
  cards, emoji as icon substitutes, Inter/Roboto as display defaults, and
  hot-linked generic stock imagery.
- Prefer hand-written CSS with custom properties; load a CDN only when the
  scenario clearly calls for it.
- Support responsive breakpoints and respect `prefers-reduced-motion`.
- Keep the two-file artifact (`index.html` + `styles.css`) so the runner can
  copy the folder cleanly.
