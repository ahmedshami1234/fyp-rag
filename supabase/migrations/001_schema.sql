-- Document Ingestion Pipeline - Simplified Database Schema
-- Run this in your Supabase SQL Editor

-- ─────────────────────────────────────────────────────────────
-- Users Table (extends Supabase auth.users)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Auto-create user profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users (id, email, full_name)
    VALUES (
        NEW.id,
        NEW.email,
        NEW.raw_user_meta_data->>'full_name'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger for new user signup
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- ─────────────────────────────────────────────────────────────
-- Topics Table
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    
    UNIQUE(user_id, name)  -- No duplicate topic names per user
);

CREATE INDEX IF NOT EXISTS idx_topics_user_id ON topics(user_id);


-- ─────────────────────────────────────────────────────────────
-- Documents Table
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,  -- Supabase Storage path
    file_type TEXT,
    chunk_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_topic_id ON documents(topic_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);


-- ─────────────────────────────────────────────────────────────
-- Row Level Security (RLS)
-- ─────────────────────────────────────────────────────────────

-- Enable RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- Users can only see their own data
CREATE POLICY "Users can view own profile" ON users
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON users
    FOR UPDATE USING (auth.uid() = id);

-- Topics policies
CREATE POLICY "Users can view own topics" ON topics
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can create own topics" ON topics
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own topics" ON topics
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own topics" ON topics
    FOR DELETE USING (auth.uid() = user_id);

-- Documents policies
CREATE POLICY "Users can view own documents" ON documents
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can create own documents" ON documents
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own documents" ON documents
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own documents" ON documents
    FOR DELETE USING (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────
-- Service Role Access (for backend)
-- ─────────────────────────────────────────────────────────────

CREATE POLICY "Service role full access users" ON users
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service role full access topics" ON topics
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service role full access documents" ON documents
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');


-- ─────────────────────────────────────────────────────────────
-- Create Storage Bucket
-- ─────────────────────────────────────────────────────────────
-- Run this separately in Supabase Dashboard > Storage > New Bucket
-- Bucket name: documents
-- Make it private
