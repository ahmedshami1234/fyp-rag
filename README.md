# Document Ingestion Pipeline

Production-level RAG document ingestion pipeline with topic-based organization.

## Features

- **Multi-format Support**: PDF, DOCX, PPTX, XLSX, TXT, HTML, Markdown, Images
- **Topic Organization**: Documents grouped by topics for focused retrieval
- **Visual Content Processing**: GPT-4o Vision summarizes images, tables, and figures
- **Semantic Chunking**: Chunks by title/heading for coherent context
- **User Isolation**: Pinecone namespaces per user for data privacy
- **Real-time Progress**: Job status tracked via Supabase Realtime
- **Automatic Trigger**: Supabase Edge Function triggers ingestion on upload

## Architecture

```
User Upload → Supabase Storage → Edge Function → FastAPI → Background Pipeline
                                                              ↓
                                                   1. Download file
                                                   2. Detect file type
                                                   3. Parse with unstructured.io
                                                   4. Chunk by title
                                                   5. Vision LLM for images
                                                   6. Generate embeddings (3072d)
                                                   7. Store in Pinecone
```

## Setup

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your credentials:
# - OPENAI_API_KEY
# - PINECONE_API_KEY
# - SUPABASE_URL
# - SUPABASE_SERVICE_KEY
```

### 3. Setup Supabase Database

Run the SQL in `supabase/migrations/001_schema.sql` in your Supabase SQL Editor.

### 4. Deploy Edge Function

```bash
# Install Supabase CLI
npm install -g supabase

# Login and link project
supabase login
supabase link --project-ref YOUR_PROJECT_REF

# Set Edge Function secrets
supabase secrets set BACKEND_URL=https://your-render-app.onrender.com

# Deploy function
supabase functions deploy on-file-upload
```

### 5. Configure Storage Trigger

In Supabase Dashboard:
1. Go to Database → Webhooks
2. Create webhook for `storage.objects` INSERT events
3. Point to your Edge Function URL

## Running Locally

```bash
# Start the server
uvicorn app.main:app --reload --port 8000

# API docs available at:
# http://localhost:8000/docs
```

## API Endpoints

### Topics
- `POST /topics` - Create topic
- `GET /topics/{user_id}` - List user's topics
- `DELETE /topics/{topic_id}?user_id=...` - Delete topic

### Documents
- `GET /documents/{topic_id}` - List documents in topic
- `DELETE /documents/{document_id}?user_id=...` - Delete document

### Ingestion
- `POST /ingest` - Start document ingestion

### Jobs
- `GET /jobs/{job_id}` - Get job status
- `GET /jobs/user/{user_id}` - List user's jobs

### Query
- `POST /query` - Semantic search within a topic

## Deployment (Render)

1. Connect your GitHub repo to Render
2. Create new Web Service
3. Set environment variables
4. Deploy!

See `render.yaml` for configuration.

## Frontend Integration

### Uploading with Topic

```javascript
// Upload file to Supabase Storage with topic metadata
const { data, error } = await supabase.storage
  .from('documents')
  .upload(`${userId}/${topicId}/${fileName}`, file, {
    upsert: false,
    metadata: {
      user_id: userId,
      topic_id: topicId
    }
  })
// Edge Function automatically triggers ingestion
```

### Monitoring Progress

```javascript
// Subscribe to job updates
supabase
  .channel('job-updates')
  .on('postgres_changes', {
    event: 'UPDATE',
    schema: 'public',
    table: 'ingestion_jobs',
    filter: `user_id=eq.${userId}`
  }, (payload) => {
    updateProgress(payload.new.progress)
  })
  .subscribe()
```

### Querying

```javascript
const response = await fetch('/query', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_id: userId,
    topic_id: topicId,
    question: "What is machine learning?",
    top_k: 5
  })
})
const results = await response.json()
```
