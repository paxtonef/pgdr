-- Proposed additive PostgreSQL migration. NOT executed by installer.
-- Existing migration 028 and its tables must exist. PGDR remains read-only.
BEGIN;
CREATE TABLE cpl.manufacturer_knowledge_document_assets (
 document_row_id UUID PRIMARY KEY REFERENCES cpl.manufacturer_knowledge_documents(document_row_id) ON DELETE CASCADE,
 manual_file TEXT NOT NULL,
 manual_sha256 TEXT NOT NULL CHECK (manual_sha256 ~ '^[0-9a-f]{64}$'),
 reviewed_content_sha256 TEXT NOT NULL CHECK (reviewed_content_sha256 ~ '^[0-9a-f]{64}$'),
 reviewer_id TEXT NOT NULL CHECK (length(trim(reviewer_id)) > 0),
 reviewer_name TEXT NOT NULL CHECK (length(trim(reviewer_name)) > 0),
 reviewed_at TIMESTAMPTZ NOT NULL,
 review_status TEXT NOT NULL CHECK (review_status IN ('approved','invalidated'))
);
CREATE TABLE cpl.manufacturer_knowledge_entry_assets (
 entry_row_id UUID PRIMARY KEY REFERENCES cpl.manufacturer_knowledge_dashboard_entries(entry_row_id) ON DELETE CASCADE,
 image_file TEXT NOT NULL,
 image_sha256 TEXT NOT NULL CHECK (image_sha256 ~ '^[0-9a-f]{64}$'),
 manual_order INTEGER NOT NULL CHECK (manual_order >= 0),
 pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
 page_reference TEXT NOT NULL CHECK (length(trim(page_reference)) > 0)
);
-- Linked warnings: numbered manual warnings attached to an entry by printed cross-references.
-- One row per (entry, warning) link, in manifest order; the same numbered warning linked to
-- two entries is stored once per entry, with identical text, so no link is lost.
CREATE TABLE cpl.manufacturer_knowledge_entry_warnings (
 warning_row_id UUID PRIMARY KEY,
 entry_row_id UUID NOT NULL REFERENCES cpl.manufacturer_knowledge_dashboard_entries(entry_row_id) ON DELETE CASCADE,
 warning_order INTEGER NOT NULL CHECK (warning_order >= 0),
 warning_number TEXT NOT NULL CHECK (length(trim(warning_number)) > 0),
 warning_text TEXT NOT NULL CHECK (length(trim(warning_text)) > 0),
 printed_page TEXT NOT NULL CHECK (length(trim(printed_page)) > 0),
 pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
 UNIQUE (entry_row_id, warning_order)
);
-- Pictograms printed inside a warning text. position = character offset in warning_text.
-- identified_entry_ids may be empty (pictogram not catalogued); identification_basis says why.
CREATE TABLE cpl.manufacturer_knowledge_warning_pictograms (
 warning_row_id UUID NOT NULL REFERENCES cpl.manufacturer_knowledge_entry_warnings(warning_row_id) ON DELETE CASCADE,
 pictogram_order INTEGER NOT NULL CHECK (pictogram_order >= 0),
 position INTEGER NOT NULL CHECK (position >= 0),
 text_before TEXT NOT NULL,
 text_after TEXT NOT NULL,
 image_file TEXT NOT NULL,
 image_sha256 TEXT NOT NULL CHECK (image_sha256 ~ '^[0-9a-f]{64}$'),
 pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
 printed_page TEXT NOT NULL CHECK (length(trim(printed_page)) > 0),
 identified_entry_ids JSONB NOT NULL CHECK (jsonb_typeof(identified_entry_ids) = 'array'),
 identification_basis TEXT NOT NULL CHECK (length(trim(identification_basis)) > 0),
 PRIMARY KEY (warning_row_id, pictogram_order)
);
COMMIT;
-- Importer MUST resolve exactly one document_row_id and one entry_row_id per entry,
-- verify the full content fingerprint, and write all rows in one transaction.
-- Importer MUST write every entry_warnings row and every inline pictogram of the export,
-- and resolve identified_entry_ids within the same document generation.
-- Any content/asset/applicability/warning/pictogram mutation MUST invalidate document review.
-- These application checks are NOT implemented by this DDL alone.
