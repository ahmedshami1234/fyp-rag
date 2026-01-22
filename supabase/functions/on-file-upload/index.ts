// Supabase Edge Function: on-file-upload
// Triggered when a file is uploaded to Supabase Storage
// Calls the FastAPI ingestion endpoint

import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

// Configure your FastAPI backend URL
const BACKEND_URL = Deno.env.get("BACKEND_URL") || "http://localhost:8000"

interface StoragePayload {
    type: "INSERT" | "UPDATE" | "DELETE"
    table: string
    record: {
        id: string
        bucket_id: string
        name: string
        owner: string
        created_at: string
        updated_at: string
        metadata: {
            topic_id?: string
            user_id?: string
            [key: string]: unknown
        }
    }
    schema: string
}

serve(async (req) => {
    try {
        // Parse the webhook payload
        const payload: StoragePayload = await req.json()

        console.log("Received storage event:", JSON.stringify(payload, null, 2))

        // Only process INSERT events
        if (payload.type !== "INSERT") {
            return new Response(
                JSON.stringify({ message: "Ignoring non-INSERT event" }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            )
        }

        const record = payload.record
        const metadata = record.metadata || {}

        // Extract required fields from metadata
        const user_id = metadata.user_id || record.owner
        const topic_id = metadata.topic_id

        if (!topic_id) {
            console.error("Missing topic_id in file metadata")
            return new Response(
                JSON.stringify({ error: "Missing topic_id in file metadata" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            )
        }

        // Construct the file URL
        const supabaseUrl = Deno.env.get("SUPABASE_URL")
        const file_url = `${supabaseUrl}/storage/v1/object/public/${record.bucket_id}/${record.name}`

        // Extract filename from path
        const file_name = record.name.split("/").pop() || record.name

        // Call the ingestion endpoint
        console.log("Calling ingestion endpoint:", `${BACKEND_URL}/ingest`)

        const response = await fetch(`${BACKEND_URL}/ingest`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                user_id: user_id,
                topic_id: topic_id,
                file_url: file_url,
                file_name: file_name,
            }),
        })

        const result = await response.json()

        if (!response.ok) {
            console.error("Ingestion failed:", result)
            return new Response(
                JSON.stringify({ error: "Ingestion failed", details: result }),
                { status: response.status, headers: { "Content-Type": "application/json" } }
            )
        }

        console.log("Ingestion started successfully:", result)

        return new Response(
            JSON.stringify({
                message: "Ingestion triggered successfully",
                job_id: result.job_id,
                document_id: result.document_id,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
        )

    } catch (error) {
        console.error("Edge function error:", error)
        return new Response(
            JSON.stringify({ error: error.message }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        )
    }
})
