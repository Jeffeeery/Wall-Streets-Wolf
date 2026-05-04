-- Run this in Supabase SQL Editor (supabase.com → your project → SQL Editor)

CREATE TABLE IF NOT EXISTS analysis_history (
  id          BIGSERIAL PRIMARY KEY,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  analysis_time TEXT NOT NULL,
  conclusion  TEXT,
  report      TEXT,
  snapshot    JSONB
);

ALTER TABLE analysis_history ENABLE ROW LEVEL SECURITY;

-- Web dashboard can read all rows (no auth required)
CREATE POLICY "anon_read" ON analysis_history
  FOR SELECT TO anon USING (true);

-- Only the backend service role can insert
CREATE POLICY "service_insert" ON analysis_history
  FOR INSERT TO service_role WITH CHECK (true);
