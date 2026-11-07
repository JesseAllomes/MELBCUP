# Working rules from the owner

- **Collect and collate data with repeatable workers that use no tokens**, wherever possible. That
  means scripts, GitHub Actions and scheduled jobs (for example `tools/live_collector.py`), not
  agents. Agents cost tokens.
- **Never start Fable without the owner asking.** Fable is reserved for complex analysis, critical
  thinking and outside-the-box thinking, and only on request. When Fable runs, scripts do the data
  collection and token burn is kept to a minimum.
- **Run substantial multi-step work under the `drainclamp-build-adhd` skill**, so its state is
  durable and tracked by milestone.
- Be mindful of credits.
- Push to main with `git push origin build/cup-day:main`.
- Keep API keys out of the repository.
- **Any secret the owner sends goes straight into Key Vault** (`kv-personal-v5ethud2i3cf`) under a
  plain name (e.g. `dunkapi-key`), never into the repo, and is read from there afterwards.
- **DrainClamp is compulsory** (owner, 2026-11-07, repeated): every session and every multi-step
  task starts with the `drainclamp-build-adhd` skill at Gate S, follows its gates (audit, state,
  checks, chunks, reset) and keeps `.agent/drainclamp-state.md` current. No work outside it, no
  drifting into ad-hoc mode, terse ADHD output.
- **product-ui is compulsory for every UI change** (`/home/user/jesseallomes/product-ui`): 3-4
  prototypes per round, wait for the owner, iterate; no production UI until the owner says BUILD;
  then write `.grok/product-ui/{theme,design,layout}.md`. Agents doing UI follow the same rule.
- **Push to main only after the owner approves that push** (main deploys live). Deploys to Azure
  only after explicit owner approval.
