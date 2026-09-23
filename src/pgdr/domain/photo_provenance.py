"""B2 photo-first: provenance markers for dashboard-photo-derived case data.

Kept in the domain package (pure constants, no behaviour) so that both the
automotive domain pack and the application layer can recognise a
photo-origin case without importing each other.

Two DISTINCT provenances exist and must never be conflated:

  * a machine visual-provider MATCH  -> Observation.source_type=PROVIDER,
    kind=PROVIDER_OBSERVATION_KIND, validated by the governed B2-V boundary;
  * a driver's own selection from the manufacturer symbol list (E5 fallback)
    -> Observation.source_type=USER, kind=USER_SELECTION_OBSERVATION_KIND,
    adapter_id=USER_SELECTION_ADAPTER_ID, machine_verified=False.
"""
from __future__ import annotations

PROVIDER_OBSERVATION_KIND = "dashboard_visual_interpretation"
USER_SELECTION_OBSERVATION_KIND = "dashboard_symbol_user_selection"

USER_SELECTION_ADAPTER_ID = "pgdr.e5.user_symbol_selection"
USER_SELECTION_SOURCE_RULE_ID = "pgdr.e5.user_symbol_selection"

# Question id of the ONE location-related question (config/questions.yaml).
LOCATION_QUESTION_ID = "Q-STATE-001"

PHOTO_ORIGIN_OBSERVATION_KINDS = frozenset({PROVIDER_OBSERVATION_KIND, USER_SELECTION_OBSERVATION_KIND})

# E5: maximum number of retakes offered after INSUFFICIENT_VISUAL_QUALITY
# (owner-approved: two).
MAX_RETAKES = 2
