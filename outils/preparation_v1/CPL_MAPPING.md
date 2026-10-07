# Notice schema v2 → existing CPL tables

This package defines and exports the mapping; it does not execute an import. `notices.py manifest.yaml --export-cpl` only emits validated JSON.

| Manifest field | CPL destination |
|---|---|
| document_id, edition, source_authority, source_locator | Same columns in manufacturer_knowledge_documents |
| title | document_title |
| vehicle.manufacturer | manufacturer AND applicability_manufacturer |
| vehicle.model / generation | applicability_model / applicability_generation |
| applicability_period_start/end/note | Same columns in manufacturer_knowledge_documents |
| entry_id, manufacturer_designation, symbol_descriptor | Same columns in manufacturer_knowledge_dashboard_entries |
| colour, state, displayed_message, audible_signal | Same columns; null means absent from source, not inferred |
| documented_meaning, documented_instruction | Same columns; instruction may be null when not documented |
| combined_with_entry_ids | Same JSONB column; references must exist in this document |
| manual_file, manual_sha256 | Proposed manufacturer_knowledge_document_assets |
| review.content_sha256, reviewer_id/name, reviewed_at/status | Proposed document-assets review columns |
| image_file, image_sha256, pdf_page, page_reference | Proposed manufacturer_knowledge_entry_assets |
| entries list position | Proposed manual_order (zero-based) |
| linked_warnings (optional per entry; absent = none) | Proposed manufacturer_knowledge_entry_warnings, one row per entry/warning link |
| linked_warnings list position | warning_order (zero-based) |
| linked_warnings[].number, text | warning_number, warning_text (exact text, stop instructions included) |
| linked_warnings[].printed_page, pdf_page | printed_page, pdf_page |
| linked_warnings[].inline_pictograms | Proposed manufacturer_knowledge_warning_pictograms |
| inline_pictograms list position | pictogram_order (zero-based) |
| inline_pictograms[].position, text_before, text_after | Same columns; position is a character offset in the warning text |
| inline_pictograms[].image_file, image_sha256, pdf_page, printed_page | Same columns |
| inline_pictograms[].identified_entry_ids, identification_basis | Same columns; ids JSONB, may be empty when the pictogram is not catalogued |

`--export-cpl` emits every linked warning under `entry_warnings` (entry_id, warning_order, all warning fields, and every inline pictogram with all its fields plus pictogram_order). Warning and pictogram key sets are exact: an unknown key rejects the manifest rather than being silently dropped. The same numbered warning attached to several entries appears once per entry. Validation checks pages, pictogram files and hashes, that each position matches text_before/text_after in the warning text, and that identified entries exist in the document. The review fingerprint already covers these fields: any change to a warning or pictogram, or its removal, makes the review obsolete.

One V1 catalogue item corresponds to one existing CPL entry and one image association. An image representing different fixed/flashing entries must have distinct entry IDs and retain the documented variants; do not collapse those entries. Identical images/texts may legitimately repeat.

Files remain relative to a curated package root. The importer must assign immutable server-side storage locations; these relative paths are not public URLs. Resolve foreign keys by a unique document generation, then unique entry ID within it, rejecting ambiguity. Do not use PostgreSQL's VERIFIED_CURRENT default as proof of review. Existing lifecycle/freshness fields retain their own governance; human approval here is not an automatic freshness admission.

`cpl/migration_assets_proposal.sql` is an additive DDL proposal, not installed or tested on PostgreSQL. Integrate into CPL's Alembic chain and models before deployment. Import must be atomic and the read adapter must revalidate the snapshot against the review fingerprint, including original field names, entry order, texts, applicability and file hashes. Any mutation invalidates review. The DDL alone does not enforce those application invariants; no completed importer is claimed.

The named review is a recorded attestation, not authenticated proof of identity. Production import must obtain reviewer identity from an authenticated account, restrict who can approve and audit approvals. A SHA256 detects changes, not malicious replacement of both data and review.
