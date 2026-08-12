# agy prompt templates

These YAML files are shipped with StreamDoc as sample templates for the agy
(Antigravity) content-generation backend. They follow the `PromptTemplate`
shape used by the NotebookLM prompt manager.

## Overrides

User overrides go to `config/prompts/agy/`. The manager loads that directory
first and falls back to the shipped samples in this directory.

## Adding prompts

Drop a new `*.yaml` file here and the prompt manager will pick it up at runtime,
subject to the loader's validation (valid YAML, `name` field, matching variable
placeholders).
