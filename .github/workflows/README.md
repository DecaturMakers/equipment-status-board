# GitHub Actions Workflows

## Workflows

### 🧪 `ci.yml` — CI
**Triggers:** Push to `main`, Pull Requests to `main`
**Jobs:** `lint` (ruff), `test` (pytest against SQLite in-memory), `screenshots-check`
(regenerates the docs screenshots with Playwright and fails if any are missing),
`docs-build` (`mkdocs build --strict`), `docker-build`.

### 📚 `docs.yml` — Documentation
Builds and publishes the MkDocs site.

### 🚀 `release.yml` — Release and Publish
**Triggers:** Push to `main`
Compares `version` in `pyproject.toml` to the latest GitHub release tag; if it is
strictly higher, pushes `ghcr.io/decaturmakers/equipment-status-board:<version>`
and `:latest`, tags `v<version>`, and creates the GitHub Release. Merges that do
not bump the version are a no-op. See the Releases section of `CLAUDE.md`.

### 🤖 `claude-pr-review.yml` and `claude-mention.yml` — Claude Code

These two look redundant and are not. **Do not delete one as a duplicate of the
other** — that happened in `d0d9a1c` and silently broke `@claude` for this repo.

| | `claude-pr-review.yml` | `claude-mention.yml` |
|---|---|---|
| **Triggers** | `pull_request` | `issue_comment`, `issues`, `pull_request_review*` + `@claude` |
| **Asked for?** | No — reviews every PR unprompted | Yes — only when you write `@claude` |
| **Action mode** | agent (a `prompt` is supplied) | tag (no `prompt`) |
| **`contents:`** | `read` | `write` — it can push fixes |

The modes are why they cannot be one job. Supplying a `prompt` puts the action
in agent mode for *every* event it sees, so a single job with both triggers
would answer `@claude` comments in agent mode: no PR context, no tracking
comment, and nothing posted back. They could share one file as two guarded jobs;
they are kept apart so each file's permissions and tools say what they mean.

`issue_comment` workflows always run from the **default branch**, so changes to
`claude-mention.yml` have no effect until they are merged to `main` — testing
them on a branch proves nothing.

The 👀 reaction on an `@claude` comment comes from the Claude GitHub App
acknowledging the mention. It is **not** evidence that anything ran — the work
happens in `claude-mention.yml`, and if that workflow is missing or not yet on
`main`, the eyes are all you ever get.

**Allowed tools:** both jobs allow `Bash` outright rather than enumerating
commands. An enumerated allowlist starves them — this project needs pytest,
ruff, `flask db`, `docker compose`, mkdocs, git and gh, and the review plugin
fans out subagents that inherit the list and reach for `sed`/`awk`/`jq`/`diff`;
every unlisted command is a silent denial. `Skill` is also load-bearing in
`claude-pr-review.yml`: `/code-review:code-review` *is* a skill, so omitting it
denies the review itself and the run improvises the plugin's steps by hand,
which is how runs went green having posted nothing.

**Artifacts:** both upload `claude-*-logs-*`, containing `execution-output.json`
(the action's own transcript) and `sessions/` (the raw Claude Code session
JSONL). The action otherwise discards these with the runner, and the job log
alone shows only `init` and `result`. Reach for these first when a run is green
but posted nothing. Note this repo is **public**, so these artifacts and the
`show_full_output` job logs are world-readable — they carry full tool output, so
don't put anything into CI you wouldn't publish.

**Re-review on new commits:** the upstream `/code-review` plugin stops without
posting if Claude has already commented on the PR, which would make every push
after the first review a silent no-op. `claude-pr-review.yml` overrides that in
its `prompt` and scopes re-reviews to the commits since Claude's last comment.

**Required secret:** `CLAUDE_CODE_OAUTH_TOKEN` (repository or organization
secret). Both workflows also need the Claude GitHub App installed on the repo.
