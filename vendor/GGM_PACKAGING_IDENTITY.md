# GGM Packaging Identity Freeze — vendor/ggm-1.2.0-py3-none-any.whl

Closes the Packaging Identity Gate opened by the PGDR -> GGM P2.2
Pre-Implementation Evidence Note v1 (§14 gate items 2/3, §15 "Packaging/
release gate: NOT YET CLOSED").

## Identity

| Field | Value |
|---|---|
| Package name | `ggm` |
| Package version | `1.2.0` |
| Wheel filename | `ggm-1.2.0-py3-none-any.whl` |
| Wheel SHA-256 | `7340c166918e5b9bb83008a8f5944ef0ae64b0c1995189fc3860d7a90b1baff2` |
| Source commit (target) | `ac99750` |
| Source archive SHA-256 | `8cf69f925dc9d97c987807a1e4452a3eeb97c119a96f8b26757844b8875b1b93` |
| Contract version (internal) | `1.3` |
| Runtime/kernel version (internal) | `ggm/1.1` |
| Resolver version (internal) | `1.3` |
| Manifest version (internal) | `1.0` |

## Provenance caveats — read before treating this as fully authoritative

1. **Source commit `ac99750` is a supplied target identity, not an
   independently git-verified one.** The source archive contains no
   `.git` metadata, so `git rev-parse HEAD` cannot recover or confirm
   this commit from the tree alone. The archive's zip comment (when
   inspected locally) began `ac997501a1a...`, which is corroborating but
   not cryptographic proof the tree matches that commit — a zip comment
   is not tied to file contents the way a commit hash is. Confirm against
   an actual `git` checkout of the GGM repository at commit `ac99750`
   before treating this identity as fully closed.

2. **Package version `1.2.0` is an externally-assigned packaging choice,
   not extracted from any canonical GGM version file** — none exists in
   the supplied source tree (`pyproject.toml`, `setup.py`, `setup.cfg`,
   `PKG-INFO` are all absent). It was chosen by this build as a MINOR bump
   from the previous vendored `ggm-1.1.0` (pre-P2.2, no `materialization`
   module, contract v1.2), reflecting that this source adds new public API
   (`ggm.materialization`) without an announced breaking change, while
   the internal runtime/kernel version (`ggm/1.1`) is unchanged.
   **This version number must be confirmed or overridden by GGM's own
   canonical build/release process** if and when one exists — do not
   propagate `1.2.0` as an authoritative GGM release version outside this
   PGDR vendor pin.

3. **The wheel was built by PGDR, not received from a canonical GGM
   release process.** `pyproject.toml` used for this build is included
   below for full reproducibility. The `ggm` package itself has zero
   third-party runtime dependencies (stdlib only — confirmed by
   inspecting every import in `ggm/**/*.py`); the source repository's
   root-level `requirements.txt` (`openai`, `pytest`) belongs to
   semantic-evaluation lab scripts outside the `ggm/` package and is not
   part of this build.

## Build reproduction

```bash
# from the GGM P2.2 source archive (SHA-256 8cf69f92...875b1b93)
mkdir ggm-build && cp -r ggm-p2-2-main/ggm ggm-build/ggm
cd ggm-build
cat > pyproject.toml <<'EOF'
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ggm"
version = "1.2.0"
description = "GGM — Generation Governance Model (P2.2, Runtime Materialization)"
requires-python = ">=3.10"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["ggm"]
EOF
python -m pip install build hatchling
python -m build --wheel --outdir dist
sha256sum dist/ggm-1.2.0-py3-none-any.whl
```

## What this closes / does not close

- **Closes**: PGDR's `vendor/` and `pyproject.toml` now reference a real,
  installable, SHA-256-identified `ggm` wheel built from the P2.2 source
  tree that the code migration was verified against — no more manual
  "copy source into site-packages" step required to run PGDR.
- **Does not close**: independent git-based confirmation of source commit
  `ac99750`, and any canonical GGM-project-issued version number, wheel,
  or release process. If GGM's own maintainers later publish an official
  `ggm` release, that release's identity should replace this one.
