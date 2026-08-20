# PGDR v2 Dependency Freeze

| Dependency | Version | Source | Commit/Hash | Required/Optional | Reason |
|---|---|---|---|---|---|
| `python` | `>=3.10` | PyPI/system | - | Required | pydantic 2 + modern type hint syntax (`X \| None`) used throughout |
| `pydantic` | `>=2.0` | PyPI | - | Required | all domain/request/response models (`models.py`, `domain/*.py`) |
| `pyyaml` | `>=6.0` | PyPI | - | Required | loading the 4 governance/domain config YAMLs |
| `rich` | `>=13.0` | PyPI | - | Required | CLI presentation (`cli.py`) |
| `click` | `>=8.0` | PyPI | - | Required | CLI command structure (`cli.py`) |
| `ggm` | `>=1.1.0` | Not on PyPI - pinned package, vendored as `vendor/ggm-1.1.0-py3-none-any.whl` | `4fda5974312f1949771fc4993ced4c98fe0d1ac0` | Required (governance defaults to enabled) | P8 - real GGM governance decisions before diagnostic presentation |
| `hatchling` | build-system only | PyPI | - | Required at build time only | wheel building |
| `pytest`, `build` | dev/test only | PyPI | - | Optional (not a runtime dependency) | test suite, wheel-build tests |

## GGM - governed as an external dependency, not PGDR code

```
package:           ggm
version:            1.1.0 (PGDR-assigned wheel version; GGM's own internal
                    RUNTIME_VERSION constant is "ggm/1.1" - a distinct,
                    intentionally separate identity, see p8_ggm_integration.md)
source commit:       4fda5974312f1949771fc4993ced4c98fe0d1ac0
contract version:    1.2   (ggm.contract.types.CONTRACT_VERSION)
resolver version:    1.3   (ggm.consumption.types.RESOLVER_VERSION)
kernel version:      ggm/1.1   (ggm.consumption.CANONICAL_KERNEL_VERSION)
wheel sha256:        f328aaa83f8f552fa40f11386f1eb461453af41acf53a1dd1ccf4bb7be7fe598
wheel contents:       ggm/ subpackage only (contract, consumption, model,
                    governance, invariants, persistence, profiles) - the
                    pinned source repo's root-level P2.2 lab/evaluation
                    scripts (semantic_provider.py, openai_semantic_provider.py,
                    sgri_validator.py, etc.) are NOT included, verified
                    by direct wheel-content inspection at build time
packaging metadata:  a minimal pyproject.toml (name="ggm", version="1.1.0")
                    was added to the pinned source purely to make it
                    pip-installable - zero changes to any ggm/*.py file
```

## Why `ggm` is a formal (not optional) dependency

`pip install pgdr-*.whl` fails loudly and immediately if `ggm` isn't
already available or co-installed, rather than succeeding and then
failing confusingly at import time (`session_controller.py` imports
`ggm.contract.interface` at module load). This trade-off was made
deliberately in P8 and is unchanged for the v2 freeze - see
`docs/architecture/p8_findings.md`.

## Reproducibility

Given the same `ggm` wheel (verified by the sha256 above) and the same
PGDR source, `resolve_pgdr_consumption_manifest()` is deterministic:
`manifest_id` is derived via `uuid5` from the three declared axes, not
randomly generated - the same manifest ID results from re-resolution on
any machine with the same pinned inputs. Confirmed live, not merely
asserted (`test_p8_t02_t03_t04_consumption_resolves_with_kernel_and_operations`
and the resolver's own `test_t05_same_input_resolves_to_semantically_identical_manifest`
in GGM's own test suite).

## What is explicitly NOT pinned

- The specific `GGMConsumer` implementation (`DefaultGGMConsumer` today)
  - injected via `GGMConsumer` Protocol, swappable without a PGDR code
  change once GGM ships a bounded/embedded runtime (P8B, see
  `PGDR_v2_DEFERRED_CAPABILITIES.md`).
- Exact patch versions of `pydantic`/`pyyaml`/`rich`/`click` - minimum
  versions only, per standard practice for a library-shaped package
  (PGDR is consumed via `install.sh` end-to-end, not published to a
  shared index where stricter pinning would matter more).
