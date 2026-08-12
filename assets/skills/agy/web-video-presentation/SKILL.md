---
name: web-video-presentation
description: Turn source content into a single-file HTML video presentation with embedded clips.
license: MIT
upstream: https://github.com/ConardLi/garden-skills#web-video-presentation
---

# Web Video Presentation

## Source

This skill adapts the `web-video-presentation` prompt from
[ConardLi/garden-skills](https://github.com/ConardLi/garden-skills#web-video-presentation),
shared under the MIT license.

## Summary

Produce a self-contained, 16:9 click-driven HTML presentation that behaves
like a cinematic video. Each click or keyboard press advances one beat; each
beat fills the screen with a focused visual idea. Source video clips are
embedded with `<video>` or `<iframe>`. The deliverable is a single
`presentation.html` file plus an optional `script.md` outline.

## Inputs

- `topic`: the subject of the presentation
- `target_audience`: who will watch it and their prior knowledge
- `source_content`: article, transcript, or notes to adapt
- `duration_minutes` (optional): rough target length, used to pace beats
- `style` (optional): visual mood/theme such as `midnight-press`, `paper-press`,
  or `warm-keynote`; if omitted, derive from the topic

## Output

Write the following in the current working directory:

- `presentation.html` — the single-file, self-contained HTML presentation
- `script.md` (optional) — narration outline used to derive beats

When complete, print one stdout line:

```text
Artifact: presentation.html
```

Exit `0` on success, non-zero on error.

## Instructions

You are a front-end presentation engineer. Turn the provided source content
into a cinematic, 16:9 web presentation named `presentation.html`.

1. Read the source files and identify the topic, audience, key beats, and any
   provided video clips.
2. If useful, write a short `script.md` narration outline with one beat per
   screen.
3. Produce `presentation.html` as a single, self-contained file:
   - Use a fixed 1920×1080 stage scaled to the viewport.
   - Each SPACE, ARROW, or CLICK advances exactly one beat.
   - Each beat owns the full screen and carries one focused idea.
   - Embed source video clips with `<video>` (local file) or `<iframe>`
     (YouTube/Vimeo) and keep them accessible.
   - Keep progress and controls hover-only so recordings stay clean.
   - Pick a visual style that fits the topic; avoid generic purple-pink
     gradients, emoji-as-icons, and AI-default Inter unless the brand demands
     them.
4. After the file is written, emit exactly one stdout line. The comment in the
   example below is explanatory; only the `Artifact:` line is actual output.

   ```text
   # Reason: the agy runner locates the produced artifact by grepping stdout for the Artifact: prefix
   Artifact: presentation.html
   ```

5. Exit `0` if the file was created; exit non-zero on any failure.

## Constraints

- No build tools, bundlers, or external CSS frameworks required; inline
  everything into `presentation.html`.
- Do not make network calls at runtime except for embedded media URLs.
- No inline JavaScript that mutates the DOM in unsafe ways; navigation and
  media controls are allowed.
- Use real clips or honest placeholders; do not fabricate media URLs.
- Maintain a single `presentation.html` artifact so the runner can copy it
  cleanly.
