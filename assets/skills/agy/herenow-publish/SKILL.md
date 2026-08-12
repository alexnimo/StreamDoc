---
name: herenow-publish
description: Publish an HTML artifact (file or directory) to here.now and return the public URL.
license: internal
upstream: https://here.now/docs
---

# here.now Publish

## Source

Internal StreamDoc skill. It wraps the official here.now publish flow
using the bundled `scripts/publish.sh` helper (vendored from
[heredotnow/skill](https://github.com/heredotnow/skill)). The script
talks to the here.now HTTP API directly via `curl` + `jq` — no separate
`herenow` CLI binary is required.

## Summary

Accept a local file or directory path, publish it to here.now as a
(anonymous by default, 24-hour expiry) site, and return the public URL
on stdout. This is the second step in the StreamDoc agy pipeline: the
content-generation skill produces an HTML artifact, then this skill
publishes it.

## Inputs

- `file_path` (positional argument): the HTML file or directory to publish.
  For directories, place `index.html` at the root.
- `--api-key` or `$HERENOW_API_KEY` (optional): here.now API key for
  permanent sites; if omitted, anonymous publish (24-hour expiry) is used.

## Output

On success, print exactly one stdout line of the form:

```text
Published: <url>
```

where `<url>` is a publicly reachable `http://` or `https://` URL. Exit
`0` on success, non-zero on failure.

## Instructions

You are a minimal wrapper around the bundled here.now publish script.

1. Read the first positional argument as the file or directory path to
   publish. If the argument is missing, write a short error to stderr and
   exit non-zero.

2. Resolve the bundled publish script. It lives next to this SKILL.md at
   `.agents/skills/herenow-publish/scripts/publish.sh` (the skills
   directory is added to the agy workspace via `--add-dir`). Use the
   absolute path to the script so it works regardless of the current
   working directory.

3. Invoke the publish script with the artifact path:

   ```text
   bash .agents/skills/herenow-publish/scripts/publish.sh <file_path>
   ```

   The script prints the live site URL on its own stdout line (e.g.
   `https://bright-canvas-a7k2.here.now/`) followed by
   `publish_result.*` metadata lines on stderr.

4. After the publish script succeeds, emit exactly one stdout line:

   ```text
   # Reason: this line is the anchor for src/streamdoc/integrations/agy/herenow.py::parse_published_url; it looks for the Published: prefix and extracts the first http(s) URL
   Published: <url>
   ```

   where `<url>` is the `https://...here.now/...` URL the script printed.

5. Exit `0` when the `Published:` line has been emitted. Exit non-zero on
   any failure, including a missing file, a failed network call, or a
   response that does not contain a URL.

## Constraints

- Do not print extra stdout lines before `Published:` unless they do not
  contain the word `Published` and do not confuse the parser.
- The URL must start with `http://` or `https://`; do not emit relative
  paths or `file://` URLs.
- Keep stderr brief and actionable.
- Anonymous publishes expire in 24 hours; do not claim to make them
  permanent unless an API key is configured.
