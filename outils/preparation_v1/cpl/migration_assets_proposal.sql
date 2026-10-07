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
COMMIT;
-- Importer MUST resolve exactly one document_row_id and one entry_row_id per entry,
-- verify the full content fingerprint, and write all rows in one transaction.
-- Any content/asset/applicability mutation MUST invalidate document review.
-- These application checks are NOT implemented by this DDL alone.
