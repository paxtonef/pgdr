# PGDR v2 Dependency Freeze

| Dependency | Version | Source | Commit/Hash | Required/Optional | Reason |
|---|---|---|---|---|---|
| `python` | `>=3.10` | PyPI/system | - | Required | pydantic 2 + modern type hint syntax (`X \| None`) used throughout |
| `pydantic` | `>=2.0` | PyPI | - | Required | all domain/request/response models (`models.py`, `domain/*.py`) |
| `pyyaml` | `>=6.0` | PyPI | - | Required | loading the 4 governance/domain config YAMLs |
| `rich` | `>=13.0` | PyPI | - | Required | CLI presentation (`cli.py`) |
| `click` | `>=8.0` | PyPI | - | Required | CLI command structure (`cli.py`) |
| `ggm` | `==1.0.0` | Not on PyPI — canonical GGM release artifact `ggm-1.0.0-py3-none-any.whl`, supplied out-of-band (not committed to this repo) | canonical release commit `5fdea20413ba85503770649cfc6df2699df8af3f`; wheel SHA-256 `414591587d29adf756f16e39ad03cffe0fa2328c8a41e5bbf3ba6b0aa42799a7` | Required (governance defaults to enabled) | P8 / P2.2 — GGM governance decisions plus canonical runtime materialization before diagnostic presentation |
| `hatchling` | build-system only | PyPI | - | Required at build time only | wheel building |
| `pytest`, `build` | dev/test only | PyPI | - | Optional (not a runtime dependency) | test suite, wheel-build tests |

## GGM — governed as an external dependency, not PGDR code

    package:             ggm
    package version:     1.0.0   (canonical)
    release commit:      5fdea20413ba85503770649cfc6df2699df8af3f
    wheel:               ggm-1.0.0-py3-none-any.whl
    wheel sha256:        414591587d29adf756f16e39ad03cffe0fa2328c8a41e5bbf3ba6b0aa42799a7
    contract version:    1.3
    resolver version:    1.3
    manifest version:    1.0
    kernel version:      ggm/1.1
    authorization:       PGDR consumption AUTHORIZED; private PGDR production
                         embedding AUTHORIZED; public redistribution NOT
                         AUTHORIZED.

The constraint is an exact pin (`ggm==1.0.0`). The historical
`ggm-1.2.0-py3-none-any.whl` (PGDR-built, source `ac99750`, SHA-256
`7340c166918e5b9bb83008a8f5944ef0ae64b0c1995189fc3860d7a90b1baff2`) is a
**NON-CANONICAL HISTORICAL PGDR PACKAGING ARTIFACT**. It is no longer the
dependency, is not tracked in git, and must not be used to establish
production governance. It is documented in `vendor/GGM_PACKAGING_IDENTITY.md`
as history only.

`ggm/1.1` is the canonical kernel/runtime identity, carried by canonical
GGM 1.0.0.

## Why `ggm` is a formal dependency

`pip install pgdr-*.whl` fails loudly if the required GGM package is not
available or co-installed.

Governance is enabled by default and PGDR requires GGM before governed
diagnostic presentation.

PGDR now acquires its default GGM consumer through the canonical P2.2
runtime materialization path:

    PGDR consumption declaration
        -> consumption resolution
        -> RuntimeMaterializer
        -> MaterializedGGMRuntime
        -> runtime.consumer

PGDR no longer constructs `DefaultGGMConsumer` directly in its default
production path.

## Runtime materialization dependency

PGDR currently declares one required GGM operation:

    DECIDE

`TRANSITION` and `CHECK_ESCALATION` are not required by current PGDR
behavior.

The GGM P2.2 `RuntimeMaterializer` owns canonical-state validation,
constructor dependency resolution, machinery selection, and bounded
runtime construction.

For the PGDR DECIDE-only manifest, verified materialization requires:

- GovernanceDecisionEngine
- ProfileResolver

and does not require:

- TransitionEngine
- EscalationDetector
- ClaimStore

PGDR SHALL therefore not pin or reproduce this internal machinery
composition as part of its own integration contract.

## Reproducibility

Given the same vendored GGM wheel and the same PGDR source,
`resolve_pgdr_consumption_manifest()` is deterministic.

`manifest_id` is derived deterministically from the declared consumption
axes.

The canonical P2.2 materialization path is verified against canonical
GGM 1.0.0 (`ggm-1.0.0-py3-none-any.whl`, SHA-256
`414591587d29adf756f16e39ad03cffe0fa2328c8a41e5bbf3ba6b0aa42799a7`)
through the complete PGDR test suite with:

    GGM_WHEEL_PATH=/path/to/ggm-1.0.0-py3-none-any.whl

Result at adoption: 492 passed, 0 skipped, 0 failed (includes real-Chromium
E2E). Earlier runs against the historical non-canonical 1.2.0 artifact
(163 passed) are history only and are not evidence of canonical governance.

## What is explicitly pinned

PGDR pins the following GGM dependency properties:

- installable GGM package artifact: `ggm-1.0.0-py3-none-any.whl` (`ggm==1.0.0`)
- wheel SHA-256 `414591587d29adf756f16e39ad03cffe0fa2328c8a41e5bbf3ba6b0aa42799a7`
- canonical release commit `5fdea20413ba85503770649cfc6df2699df8af3f`
- public consumption contract required by PGDR
- public runtime materialization capability
- DECIDE as the required PGDR GGM operation
- embedded/offline/standalone consumption requirements

## What is explicitly NOT pinned

PGDR does not pin GGM's internal machinery composition beyond the public
contract required to satisfy its consumption declaration.

In particular, PGDR does not own or pin:

- internal engine constructor dependencies
- internal machinery selection
- presence of TransitionEngine when DECIDE does not require it
- presence of EscalationDetector when DECIDE does not require it
- ClaimStore when persistence is not required

Those are provider-owned properties resolved by GGM RuntimeMaterializer.

Exact patch versions of `pydantic`, `pyyaml`, `rich`, and `click` are also
not pinned; PGDR retains minimum-version constraints for those ordinary
library dependencies.
