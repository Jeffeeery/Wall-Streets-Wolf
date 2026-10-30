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

-- v3 消息面简报：已有表执行以下语句即可（未执行时后端会自动退回旧字段写入）
ALTER TABLE analysis_history ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE analysis_history ADD COLUMN IF NOT EXISTS sources   JSONB;
ALTER TABLE analysis_history ADD COLUMN IF NOT EXISTS outlook   JSONB;
