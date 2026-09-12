# Releasing with tags

How to cut a release of Agentic Paper Explorer so the `backend`, `ingestion`, and `frontend` images
get built and published to Docker Hub. See [.github/workflows/ci.yaml](../.github/workflows/ci.yaml)
and [.github/workflows/release.yaml](../.github/workflows/release.yaml) for the workflows this guide
walks through.

## How releases are triggered

`release.yaml` runs in two cases:

- **Push to `main`** - builds and pushes all three images tagged `:latest` and with the commit SHA.
  This happens on every merge to `main`, so `main` always has a corresponding set of images.
- **Push of a `v*` tag** (for example `v0.2.0`) - builds and pushes the same three images, additionally
  tagged with the semver version from the tag.

Either way, `release.yaml` first calls `ci.yaml` as a required check (lint, `bandit`, secret scan,
tests, container build). If that fails, nothing gets published.

A **tag is what marks an actual, named release** - use one when you want a version number you can
point back to (changelog entry, rollback target, "what's running in prod"), not for every merge to
`main`.

## Versioning scheme

Use [Semantic Versioning](https://semver.org/): `vMAJOR.MINOR.PATCH`, for example `v0.3.1`.

- **MAJOR** - breaking change to the API contract, config, or deployment topology.
- **MINOR** - new feature or phase delivered (for example, adding guardrails or orchestration).
- **PATCH** - bug fix or small internal change, no behavior contract change.

The project is pre-1.0 (`v0.x.y`), so treat MINOR bumps as the normal case and MAJOR as reserved for
a stable-API milestone.

## Step-by-step: cutting a release

Assumes your branching model from here: feature branch → PR into `dev` → PR into `main`.

1. **Confirm `main` is what you want to release.**
   ```bash
   git checkout main
   git pull origin main
   ```
2. **Decide the next version number.** Check the latest tag:
   ```bash
   git tag --sort=-v:refname | head -5
   ```
   Pick the next version following the scheme above.
3. **Create an annotated tag** (annotated, not lightweight, so it carries a message and author):
   ```bash
   git tag -a v0.2.0 -m "Phase 7: CI/CD and Docker Hub publishing"
   ```
4. **Push the tag** - this is what triggers `release.yaml`:
   ```bash
   git push origin v0.2.0
   ```
5. **Watch the run** in the repo's Actions tab. `ci` must pass before `publish` starts.
6. **Verify the images** landed on Docker Hub under
   `<dockerhub-user>/agentic-paper-explorer-<backend|ingestion|frontend>`, tagged `v0.2.0` and
   `latest`.
7. **Write the release notes** on GitHub (Releases → Draft a new release → select the tag) summarizing
   what changed, referencing the relevant [docs/phases](phases) entry.

## Best practices

- **Tag from `main` only.** Tagging a feature or `dev` branch commit makes the release history
  confusing and can publish images that never went through the full PR review.
- **One tag, one release.** Do not move or force-push a tag to point at a different commit once it
  has been pushed - create a new patch version instead. Re-pointing a tag can silently change what
  `:latest` consumers pull.
- **Never delete a published tag** that has corresponding images on Docker Hub unless you are
  deliberately retracting a broken release, and say so in the release notes if you do.
- **Keep `CHANGELOG` context in the tag message or GitHub release notes**, not just the commit
  message - it is what people read six months later to understand what `v0.2.0` actually contains.
- **Let CI gate the tag.** Do not add `--no-verify` or otherwise bypass `ci.yaml` to force a tag
  through if checks fail; fix the failure and re-tag with the next patch version instead.
- **`latest` always tracks `main`.** If you need to know what a specific tag contains, use the tag,
  not `latest` - `latest` is a moving target by design.

## Rolling back

If `v0.2.0` turns out to be broken in production, do not delete or reuse the tag. Deploy the last
known-good tag instead (`v0.1.0`), then fix forward with a new `v0.2.1` once the issue is resolved.
