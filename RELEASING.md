# Releasing omnigent

omnigent ships **three PyPI packages that version-lock together**:

| Package | What it is |
| --- | --- |
| `omnigent` | core wheel (bundles the `web` web UI) |
| `omnigent-client` | Python client SDK |
| `omnigent-ui-sdk` | terminal UI SDK |

`pip install omnigent==X` must resolve `omnigent-client==X` and
`omnigent-ui-sdk==X`. The pins are **lockstep** (the three packages co-version and
pin each other with `==`), so every release builds and publishes **all three at
one identical version**.

Releases are driven by **workflow dispatches, not by hand** (design:
`designs/RELEASE-AUTOMATION.md`). Every workflow below is idempotent —
re-dispatch with identical inputs after any failure and it converges — and
every dispatch requires the **admin or maintain** role on this repo.

## Where things run

- **Source of truth** (versions, tags, GitHub Releases): **`omnigent-ai/omnigent`**
  — use the **OSS GitHub account** (the personal account with push/release rights
  on the public repo).
- **Publishing to PyPI**: the central **secure-release repo**
  **`databricks/secure-public-registry-releases-eng`**, `omnigent` workflow —
  use the **Databricks EMU account**. Publishing runs on hardened runner
  groups with **OIDC Trusted Publishing (no stored secrets)** and a **mandatory
  dependency scan**. This is why we don't publish from `omnigent-ai/omnigent`,
  and why the pipeline is two dispatches per phase rather than one.

> The exact account handles — and how to request publish access — live in the
> internal release wiki; this public runbook refers to them only by role.

The legacy `.github/workflows/release-omnigent.yml` in this repo is a
**deprecated manual fallback only** — its tag-push trigger was removed so a tag
never double-publishes. Use the secure repo for real releases.

## Versioning model

- `main` always carries the **next** version with a `.dev0` suffix
  (e.g. `0.6.0.dev0`) — never a clean released number. This matches
  MLflow / Delta / Unity Catalog and keeps every `main` build PEP 440-ordered as
  "ahead of the last release, not yet the next one".
- Releases are cut on **per-minor release branches** (`branch-X.Y`) and tagged
  there (`vX.Y.Z`, rc tags `vX.Y.ZrcN`); patches (`vX.Y.1`, `vX.Y.2`, …) are
  cherry-picked onto the same `branch-X.Y`. `main` is never tagged.
- Every release ships as an **rc first** (`0.6.0rc1` → … → `0.6.0`). rcs go to
  **real PyPI** as PEP 440 pre-releases — a default `pip install omnigent`
  never resolves them, and testers install with exact pins. TestPyPI is no
  longer part of the standard flow.

## Docs staging

Because `main` carries the **next** version, the docs generated from merged PRs
describe a release that isn't out yet — so they must **not** deploy to the live
site on merge. Two workflows enforce this by staging onto a **per-minor docs
branch** on `omnigent-site` instead of `main`:

- **`doc-sync.yml`** — drafts prose docs for each merged PR that needs them.
- **`sync-openapi-to-site.yml`** — syncs the API reference (`openapi.json`).

Both derive the branch name from `omnigent/version.py` (`0.6.0.dev0` → `0.6-docs`)
and create it off site `main` the first time a doc PR lands in the cycle. All docs
for the `0.6` line — including patches — accumulate on `0.6-docs`. Each PR still
gets its own review, but merging one only lands it on the staging branch, not the
live site. At finalize time, the whole batch goes live at once (step 4 below).

---

## Standard flow

### rc phase (example: `0.6.0rc1`)

**1. Cut + tag — dispatch `Release` (`release.yml`), OSS account.**

```bash
gh workflow run release.yml --repo omnigent-ai/omnigent \
  -f version=0.6.0rc1 -f dry_run=false
# optional: -f ref=<sha> to cut branch-0.6 from a specific commit (rc1 only);
# dry_run defaults to true — run once without -f dry_run to preview the plan.
```

What it does (all idempotent):

- asserts green CI on the base commit (escape hatch for a flaky check:
  `-f skip_ci_check=true`, use deliberately);
- creates `branch-0.6` from `ref` (rc1) or reuses the existing branch head
  (rc2+, final, patches — `ref` is ignored then);
- stamps the lockstep version via `scripts/update_versions.py` and regenerates
  `uv.lock` with a clean public-PyPI resolution — **never hand-edit `uv.lock`
  or run `uv lock` behind a proxy**; the workflow owns this now;
- commits `release: v0.6.0rc1`, tags, and pushes branch + tag with the
  omnigent-ci App token, which fires the downstream automation:
  `github-release.yml` (draft GH release, pre-release flagged),
  `draft-release-notes.yml`, and `oss-publish-images.yml` (Docker);
- on the **first** cut of a cycle (rc1), dispatches `bump-version.yml`
  (post-release) — **review and merge the `main → 0.7.0.dev0` bump PR
  promptly**, so `doc-sync` keeps staging to the right docs branch.

**2. Publish to PyPI — dispatch the secure repo (EMU account).**

```bash
gh auth switch --user <emu-account>
gh workflow run omnigent.yml --repo databricks/secure-public-registry-releases-eng \
  -f ref=v0.6.0rc1 -f destination=pypi -f dry-run=true    # gates rehearsal
gh workflow run omnigent.yml --repo databricks/secure-public-registry-releases-eng \
  -f ref=v0.6.0rc1 -f destination=pypi -f dry-run=false   # real publish
```

The dry run exercises build + dependency scan + the gates (lockstep
version/pins, web-UI-in-wheel, `twine check`, smoke-install) and the OIDC
token exchange without uploading. The real run binds the per-package
Trusted-Publisher environments (may gate on reviewer approval) and re-verifies
that `ref` is exactly the tag and points at the built commit.

**3. Validate from PyPI** (clean venv; exact pins resolve pre-releases):

```bash
python -m venv /tmp/omni-rc && /tmp/omni-rc/bin/pip install \
  --index-url https://pypi.org/simple/ \
  omnigent==0.6.0rc1 omnigent-client==0.6.0rc1 omnigent-ui-sdk==0.6.0rc1
/tmp/omni-rc/bin/omnigent --version    # expect 0.6.0rc1
```

The rc's GitHub draft stays **unpublished** — rc drafts are never published.
Need another candidate? Repeat with `0.6.0rc2` (fixes land on `branch-0.6`
first, via cherry-pick PRs or direct pushes; CI runs on `branch-*` pushes).

### Final phase (example: `0.6.0`)

1. **Cut + tag**: `gh workflow run release.yml -f version=0.6.0 -f dry_run=false`
   — same as above; builds from the `branch-0.6` head.
2. **Publish to PyPI**: same secure-repo dispatches on `ref=v0.6.0`.
3. **Curate**: merge the `CHANGELOG.md` PR that `draft-release-notes.yml`
   opened, and review/trim the curated notes in the `v0.6.0` draft on the
   Releases page — whatever you leave becomes the website post.
4. **Finalize — dispatch `Finalize release` (`finalize-release.yml`)**:

   ```bash
   gh workflow run finalize-release.yml --repo omnigent-ai/omnigent -f tag=v0.6.0
   ```

   It verifies PyPI serves all three packages, the CHANGELOG PR isn't open,
   and the **docs sweep**: no open PRs against `0.6-docs` on `omnigent-site`
   (it lists any stragglers — get them reviewed and merged/closed, then
   re-dispatch). Then it pauses on the **`publish-release` environment**;
   approving it attests "I reviewed the draft notes". It publishes the release
   as **Latest**, which fires:
   - `publish-changelog.yml` → the site **release-post PR** and the
     **`0.6-docs → main` docs-publish PR** — review and merge both;
   - `update-homebrew.yml` → the **homebrew-tap bump PR** (new sdist pin +
     regenerated resources; test-bot builds the bottles on it) — review the
     resource diff, then apply the **`pr-pull`** label to bottle + merge.

### Patch release (example: `0.6.1`)

Cherry-pick the fixes onto `branch-0.6` (CI runs on the push), then run the
same flow with `version=0.6.1` — an rc first if the patch warrants one. `main`
does not change for a patch, and a patch never needs a new branch.

---

## One-time setup (repo admin)

- **`publish-release` environment** on `omnigent-ai/omnigent` with required
  reviewers = the release managers. Without it the finalize publish job runs
  ungated.
- **omnigent-ci App** installed on `omnigent-ai/homebrew-tap` (it already
  covers `omnigent` and `omnigent-site`).
- **Tag ruleset** (recommended): restrict `v[0-9]*` create/update/delete to
  the omnigent-ci App + admins, so no write-access account can start the
  tag-push automation by hand.

## If a publish goes wrong (recovery)

**PyPI releases can't be deleted, only _yanked_**, and a version number once used
can never be reused. So:

- **Any workflow failed mid-run:** fix the cause and **re-dispatch with the
  same inputs** — every step converges (branch exists → reused; version
  stamped → no new commit; tag at the converged commit → no-op) or fails
  loudly (tag elsewhere) rather than duplicating work.
- **Wrong commit tagged, nothing published yet:** delete the tag and draft
  (`gh release delete vX.Y.Z`, `git push origin :refs/tags/vX.Y.Z`), then
  re-dispatch `release.yml`.
- **rc is bad:** just cut the next rc — rcs are cheap and invisible to
  default installs.
- **Prod publish partially succeeded** (e.g. two of three packages uploaded):
  **yank** the published version(s) on PyPI (each affected project → *Manage* →
  *Releases* → *Yank*) so installs don't resolve a half-published set, then cut
  the next version with the fix. Don't try to overwrite — Trusted Publishing /
  `twine` rejects re-uploading an existing version.
- Publishing uses **OIDC Trusted Publishing (no stored secrets)**, so a failed
  run leaks nothing — fix forward to the next version.

---

## Break-glass appendix (manual fallback)

If the workflows are unavailable, the flow can be driven by hand — but keep two
rules even then:

1. **Never hand-edit `uv.lock` and never run `uv lock` behind a proxy.** Use
   `bump-version.yml` (mode `pre-release`, `base_branch=branch-X.Y`) to
   produce the bump as a PR with a cleanly regenerated lockfile, and merge it.
2. **Push tags from an account, not automation you improvised** — the tag push
   must fire `github-release.yml` et al., which a `GITHUB_TOKEN`-authored push
   would not.

```bash
gh auth switch --user <oss-account>
git fetch origin && git checkout -b branch-0.6 origin/main   # rc1 only
gh workflow run bump-version.yml -f mode=pre-release -f new_version=0.6.0rc1 \
  -f base_branch=branch-0.6                                  # then merge the PR
git fetch origin && git checkout branch-0.6 && git pull
git tag v0.6.0rc1 && git push origin branch-0.6 v0.6.0rc1    # explicit tag, NOT --tags
```

Then continue from step 2 of the standard flow (secure-repo dispatches). If the
GH draft wasn't created, `gh release create vX.Y.Z --draft --verify-tag
--title vX.Y.Z` recreates it. To re-run the notes/site halves for an existing
tag, dispatch `draft-release-notes.yml` or `publish-changelog.yml` with the
`tag` input; for the tap, dispatch `update-homebrew.yml`.
