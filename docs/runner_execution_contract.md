# PGDR Runner Execution Contract (REC) — v1

This document explains `runner_execution_contract.yaml` in prose. The YAML
file is the source of truth; this document is a guide to reading it, not a
second, independently-maintained copy of its content.

## What this document is (and isn't)

The REC describes **PGDR's actual, currently-verified execution behavior**.
It does not describe planned features, the v2 roadmap (generic diagnostic
engine, Vehicle Health Record, CGM, RGM/RGG, LLM integration, persistence
layer), or anything aspirational. If a capability doesn't exist in the code
today, the REC says so explicitly — e.g. `interfaces.api.available: false`
— rather than staying silent on the topic or hinting at future plans.

This discipline matters more than it might seem: a contract that quietly
omits "we don't have X" reads, to an operator, identically to a contract
that was never asked about X. Explicit `false`/`required: false`/
`available: false` is the only honest way to represent "we checked, and no."

## Liveness vs. Readiness

These are different questions, and PGDR (from P1 onward) answers them
differently:

```
LIVENESS
"Is the process alive?"
→ Trivially true if this Python code is executing at all.
→ PGDR v0.1 is a single-invocation CLI, not a long-running service, so
  there is no separate liveness probe to run — there's no daemon to poll.

READINESS
"Can PGDR safely accept diagnostic work right now?"
→ Requires: packaged configuration valid, safety engine operational,
  all required capabilities constructed successfully.
→ Checked by pgdr.readiness.check_readiness() — see below.
```

A PGDR process can be **LIVE** (the interpreter started, `import pgdr`
worked) while being **NOT READY** (its safety configuration is invalid).
Before P1, this distinction wasn't formalized anywhere in code — P0 made
config failures fail closed (raise `ConfigurationError`, never fabricate a
verdict), and P1 gives that failure a name and a queryable, testable
mechanism (`READY` / `NOT_READY`) instead of only surfacing as an exception
at the one place (`SessionController()` construction) that happened to
trigger it.

## How to check readiness

```bash
pgdr readiness                 # human-readable panel, exit 0 (READY) or 1 (NOT_READY)
pgdr readiness --json-output   # machine-readable, same exit code contract
```

Or programmatically:

```python
from pgdr.readiness import check_readiness

report = check_readiness()
if not report.ready:
    print(report.reason)       # e.g. FailureReason.CONFIGURATION_ERROR
    for check in report.checks:
        print(check.name, check.status, check.detail)
```

## What "required" currently means

As of P1, PGDR has exactly **3 required readiness checks** and **0 optional
capabilities**:

| Check | What it proves |
|---|---|
| `packaged_resources_and_configuration` | All 4 governance YAML files (safety_rules, symptom_taxonomy, questions, business_rules) are present and load without error; safety_rules.yaml additionally passes full semantic validation (P0.3). |
| `safety_engine` | `SafetyEngine()` constructs successfully and has at least one rule loaded. Tracked separately from the generic config check above because "is the safety envelope operational" is the single most important readiness question PGDR can answer — even though today, both checks happen to be driven by the same file. |
| `session_controller` | A full `SessionController()` constructs successfully — this transitively exercises the complaint parser, diagnostic engine, question bank, and report builder, i.e. every remaining required capability at once. |

There is no optional-capability list to show today because PGDR v0.1
genuinely doesn't have one. The readiness mechanism (`check_readiness()`)
does support supplying additional checks marked `required=False` — this
exists so the *mechanism itself* (specifically: "an optional check failing
must never block readiness") is testable without inventing a PGDR
capability that doesn't exist in production. See
`tests/test_p1_readiness.py`.

## Failure semantics

```
READY
    All required checks passed.

NOT_READY
    Generic: at least one required check failed.

    ├── CONFIGURATION_ERROR
    │   A required YAML was missing / empty / malformed, or
    │   safety_rules.yaml failed semantic validation.
    │
    ├── SAFETY_ENGINE_UNAVAILABLE
    │   SafetyEngine failed to construct, or has zero rules.
    │   Reported with priority when multiple checks fail at once.
    │
    └── CAPABILITY_UNAVAILABLE
        A required capability failed for a reason that ISN'T a
        ConfigurationError — e.g. an unexpected bug during
        construction. Distinguishes "the config is bad" from
        "something else broke."
```

Today, `CONFIGURATION_ERROR` and `SAFETY_ENGINE_UNAVAILABLE` mostly overlap
in practice — the only way PGDR currently fails to be READY is a bad
`safety_rules.yaml`. `CAPABILITY_UNAVAILABLE` exists for a failure mode
PGDR doesn't currently have a concrete example of, but the mechanism
handles it correctly if it ever occurs (proven by injecting a non-
`ConfigurationError` exception in tests — see
`test_safety_engine_initialization_failure_that_is_not_a_configuration_error`).

## What's explicitly NOT in scope for P1

Per the development mandate this phase was built against:

- No change to diagnostic logic, `SafetyEngine` business rules, or any
  existing rule/hypothesis/report behavior.
- No LLM, database, persistence layer, Vehicle Health Record, CGM, or
  RGM/RGG — none of these exist in the codebase, and this phase doesn't
  add them.
- No generalization toward a machine-agnostic diagnostic engine, and no
  refactor of the automotive domain logic.

P1 is intentionally "small and boring": it formalizes the execution
contract PGDR *already* satisfies, and provides automated proof of it —
nothing more.
