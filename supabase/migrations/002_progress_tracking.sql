-- Progress Tracking Migration
-- Run this in your Supabase SQL Editor to add progress tracking columns

-- Add progress tracking columns to documents table
ALTER TABLE documents 
ADD COLUMN IF NOT EXISTS processing_stage TEXT;

ALTER TABLE documents 
ADD COLUMN IF NOT EXISTS progress_percent INTEGER DEFAULT 0;

ALTER TABLE documents 
ADD COLUMN IF NOT EXISTS stage_details TEXT;

-- Add index for faster status queries
CREATE INDEX IF NOT EXISTS idx_documents_processing_stage ON documents(processing_stage);

-- Comment for documentation
COMMENT ON COLUMN documents.processing_stage IS 'Current pipeline stage: downloading, parsing, chunking, vision, embedding, storing, done';
COMMENT ON COLUMN documents.progress_percent IS 'Progress percentage 0-100';
COMMENT ON COLUMN documents.stage_details IS 'Additional details like "Processing image 3 of 5"';
