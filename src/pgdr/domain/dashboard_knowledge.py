"""Block B2-K — Vehicle-Specific Dashboard Knowledge, domain types.

Establishes: VIR canonical vehicle identity -> document applicability ->
applicable manufacturer document -> Dashboard Reference Set. Does NOT
interpret an image (that is B2-V) and does NOT diagnose (that is PGDR's
own downstream reasoning).

HONESTY NOTE ON SOURCE ACCESS (read before trusting any fixture data this
module or its adapters ship with): this execution environment has no web
access tool (no web_search, no web_fetch) and therefore cannot retrieve or
verify the actual authorized Peugeot 3008/5008 handbook / Service Box
content. Per the mandate's own §8/§14 discipline ("do not silently treat
[a model] as the source of dashboard meaning", "the repository must not
become a duplicate of the handbook"), no fixture data anywhere in this
module's adapters may be presented as verified Peugeot-sourced text.
Every such fixture is explicitly tagged SourceAuthority.UNVERIFIED_
PLACEHOLDER, never SourceAuthority.MANUFACTURER_OFFICIAL, until real
sourced content is supplied by someone with actual access to it. The
architecture itself (Port, domain types, adapter, applicability engine)
is real and load-bearing; the shipped example data is deliberately not.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ApplicabilityStatus(str, Enum):
    """The six states §17 of the original B2-K mandate require -- never
    collapsed into a generic failure. Extended by the Knowledge
    Persistence mandate (§10) with three more values that are genuinely
    new (persistence/freshness concepts the original applicability
    decision had no need for) -- reusing this single enum rather than
    introducing a parallel "KnowledgeStatus" type, per that mandate's own
    explicit instruction to reuse an existing equivalent rather than
    duplicate. The mandate's own VERIFIED_KNOWLEDGE_AVAILABLE /
    KNOWLEDGE_NOT_AVAILABLE / KNOWLEDGE_APPLICABILITY_UNCERTAIN map
    directly onto REFERENCE_SET_AVAILABLE / DOCUMENTATION_NOT_AVAILABLE /
    DOCUMENT_APPLICABILITY_UNCERTAIN below -- no new members needed for
    those three."""
    VEHICLE_IDENTITY_INSUFFICIENT = "vehicle_identity_insufficient"
    DOCUMENTATION_NOT_AVAILABLE = "documentation_not_available"
    MULTIPLE_DOCUMENTS_APPLICABLE = "multiple_documents_applicable"
    DOCUMENT_APPLICABILITY_UNCERTAIN = "document_applicability_uncertain"
    DASHBOARD_REFERENCE_NOT_FOUND = "dashboard_reference_not_found"
    REFERENCE_SET_AVAILABLE = "reference_set_available"
    # --- Knowledge Persistence mandate additions (§10) ---
    KNOWLEDGE_STALE = "knowledge_stale"
    SOURCE_UPDATE_REQUIRED = "source_update_required"
    SOURCE_UNAVAILABLE = "source_unavailable"


class KnowledgeLifecycleStatus(str, Enum):
    """§8.B: distinguishes knowledge currently usable from knowledge
    retained only historically. Mirrors cpl.runner_artifacts' own
    artifact_status convention in spirit (CREATED/VALIDATED/SUPERSEDED/
    REJECTED) without reusing that table (forbidden -- see the Knowledge
    Persistence Investigation's own finding on execution_id coupling)."""
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class SourceAuthority(str, Enum):
    """Distinguishes verified manufacturer-sourced content from
    placeholder/illustrative content this execution could not verify (see
    module docstring). A future adapter backed by real, licensed
    manufacturer content would use MANUFACTURER_OFFICIAL; nothing in this
    POC's own shipped fixture is entitled to that value."""
    MANUFACTURER_OFFICIAL = "manufacturer_official"
    UNVERIFIED_PLACEHOLDER = "unverified_placeholder"


class IndicatorState(str, Enum):
    """§16: a symbol's documented meaning can depend on its state, not
    only its identity -- fixed vs flashing is the canonical example the
    mandate itself gives."""
    FIXED = "fixed"
    FLASHING = "flashing"
    UNKNOWN = "unknown"


class VehicleApplicabilityContext(BaseModel):
    """§7: reuses the actual vehicle identity fields already reaching
    PGDR via VehicleIdentityContext.vehicle_identity -- no parallel
    identity model. Every field mirrors what
    product_integration/pgdr/handoff_mapper.py already dumps from VIR's
    real CanonicalVehicleIdentity. Unknown fields stay None -- never
    inferred (§7/§22)."""
    model_config = ConfigDict(frozen=True)

    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    generation: Optional[str] = None
    production_year: Optional[int] = None
    production_start_date: Optional[str] = None
    production_end_date: Optional[str] = None
    fuel_primary_type: Optional[str] = None
    engine_commercial_name: Optional[str] = None
    engine_code: Optional[str] = None
    engine_displacement_cc: Optional[int] = None
    engine_power_kw: Optional[float] = None
    transmission_type: Optional[str] = None
    transmission_gears: Optional[int] = None
    drivetrain: Optional[str] = None
    trim: Optional[str] = None
    variant: Optional[str] = None
    # §9: no first-registration date is fabricated when VIR does not
    # supply one -- this field exists so an adapter CAN use it when VIR
    # eventually does, without ever inventing a value in its absence.
    first_registration_date: Optional[str] = None

    @classmethod
    def from_pgdr_vehicle_identity_dict(cls, vehicle_identity: Optional[dict]) -> "VehicleApplicabilityContext":
        """Builds this context from exactly the dict already present on
        pgdr.models.VehicleIdentityContext.vehicle_identity (the full
        VIR CanonicalVehicleIdentity, JSON-dumped -- confirmed by direct
        source read of handoff_mapper.py::map_resolution during the B2-K
        investigation). Missing/absent nested structures degrade to None
        fields, never fabricated values."""
        vi = vehicle_identity or {}
        production = vi.get("production") or {}
        fuel = vi.get("fuel") or {}
        engine = vi.get("engine") or {}
        transmission = vi.get("transmission") or {}
        return cls(
            manufacturer=vi.get("manufacturer"),
            brand=vi.get("brand"),
            model=vi.get("model"),
            generation=vi.get("generation"),
            production_year=production.get("year"),
            production_start_date=production.get("start_date"),
            production_end_date=production.get("end_date"),
            fuel_primary_type=fuel.get("primary_type"),
            engine_commercial_name=engine.get("commercial_name"),
            engine_code=engine.get("engine_code"),
            engine_displacement_cc=engine.get("displacement_cc"),
            engine_power_kw=engine.get("power_kw"),
            transmission_type=transmission.get("type"),
            transmission_gears=transmission.get("gears"),
            drivetrain=vi.get("drivetrain"),
            trim=vi.get("trim"),
            variant=vi.get("variant"),
            first_registration_date=None,  # not currently supplied anywhere in the VIR->PI->PGDR chain
        )


class ApplicabilityPeriod(BaseModel):
    """§9/§18: a document's applicability may be bounded by production or
    first-registration date ranges, distinct from the vehicle's own
    production-date fields above -- kept as its own type so an adapter can
    represent overlapping/ambiguous editions honestly."""
    model_config = ConfigDict(frozen=True)

    start_date: Optional[str] = None
    end_date: Optional[str] = None
    note: Optional[str] = None


class ManufacturerDocumentReference(BaseModel):
    """§10.A. A specific manufacturer document/edition a Dashboard
    Reference Set's entries may be drawn from.

    Extended by the Knowledge Persistence mandate (§8) with the minimum
    lifecycle semantics required for persistent, versioned manufacturer
    knowledge -- all three optional/defaulted so every pre-persistence
    B2-K construction site remains valid unchanged:
      lifecycle_status: currently usable vs historically retained (§8.B)
      verified_at: when this generation was last confirmed against its
        source (§8.C) -- an explicit freshness marker, not itself a
        staleness POLICY (this domain type states facts; deciding a
        generation IS stale, and what to do about it, is repository/
        adapter-level reasoning, not encoded here)
      supersedes_document_id: the document_id of the generation this one
        replaces, if any (§9) -- append-only in spirit: superseding never
        deletes or mutates the prior record
    """
    model_config = ConfigDict(frozen=True)

    manufacturer: str
    document_id: str
    document_title: str
    edition: Optional[str] = None
    applicability_period: Optional[ApplicabilityPeriod] = None
    source_authority: SourceAuthority
    source_locator: str
    lifecycle_status: KnowledgeLifecycleStatus = KnowledgeLifecycleStatus.ACTIVE
    verified_at: Optional[str] = None
    supersedes_document_id: Optional[str] = None


class DashboardReferenceEntry(BaseModel):
    """§10.B / §16: deliberately NOT a one-symbol-one-meaning mapping --
    colour, state, displayed message, and audible signal are all separate,
    optional fields precisely so an adapter can represent that the same
    indicator identity means different things under different
    combinations, per the mandate's own explicit instruction not to force
    1:1 semantics."""
    model_config = ConfigDict(frozen=True)

    entry_id: str
    manufacturer_designation: str
    symbol_descriptor: Optional[str] = None
    colour: Optional[str] = None
    state: Optional[IndicatorState] = None
    displayed_message: Optional[str] = None
    audible_signal: Optional[str] = None
    documented_meaning: str
    documented_instruction: Optional[str] = None
    applicability: ManufacturerDocumentReference
    combined_with_entry_ids: list[str] = Field(default_factory=list)
    """§15.C / §16: for multi-signal patterns (e.g. an SCR/AdBlue warning
    that only carries its documented meaning in combination with another
    indicator/message) -- references other DashboardReferenceEntry.
    entry_id values within the same DashboardReferenceSet. Empty for a
    standalone entry."""


class DashboardReferenceSet(BaseModel):
    """§10.C. The B2-K terminal output. NOT Evidence, NOT Observation --
    manufacturer reference knowledge only (§20)."""
    model_config = ConfigDict(frozen=True)

    vehicle_applicability: VehicleApplicabilityContext
    candidate_documents: list[ManufacturerDocumentReference] = Field(default_factory=list)
    entries: list[DashboardReferenceEntry] = Field(default_factory=list)
    applicability_status: ApplicabilityStatus
    provenance_note: Optional[str] = None
