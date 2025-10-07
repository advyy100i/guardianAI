'use strict';

// Simplified emergency webhook (Twilio fully removed) – only raw JSON intake & face match endpoints.
const express = require('express');
const { createClient } = require('@supabase/supabase-js');

const DEFAULT_FACE_MATCH_LIMIT = 5;
const MAX_FACE_MATCH_LIMIT = 20;

function clonePayload(payload) {
  try { return JSON.parse(JSON.stringify(payload ?? null)); } catch { return payload; }
}
function ensureEmbeddingArray(value) {
  if (!Array.isArray(value) || value.length === 0) return null;
  const parsed = value.map(Number); if (parsed.some((n)=>Number.isNaN(n))) return null; return parsed;
}
function normalizeMatchLimit(value, fallback) {
  const parsed = Number.parseInt(value, 10); if (Number.isNaN(parsed) || parsed <= 0) return fallback; return Math.min(parsed, MAX_FACE_MATCH_LIMIT);
}

// Router factory
function createEmergencyRouter(config = {}) {
  const router = express.Router();
  router.use(express.json({ limit: '5mb' }));

  const supabaseUrl = config.supabaseUrl ?? process.env.SUPABASE_URL;
  const supabaseKey = config.supabaseKey ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !supabaseKey) {
    throw new Error('Supabase credentials missing (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).');
  }
  const supabase = createClient(supabaseUrl, supabaseKey);

  const faceMatchFn = config.faceMatchFn ?? process.env.SUPABASE_FACE_MATCH_FUNCTION ?? 'match_face_embeddings';
  const faceMatchDefaultLimit = normalizeMatchLimit(
    process.env.FACE_MATCH_DEFAULT_LIMIT,
    DEFAULT_FACE_MATCH_LIMIT
  );

  router.post('/face-matches', async (req, res) => {
    if (!faceMatchFn || faceMatchFn.toLowerCase() === 'disabled') {
      return res.status(503).json({ error: 'Face matching RPC not configured.' });
    }

    const embedding = ensureEmbeddingArray(
      req.body?.embedding ?? req.body?.vector ?? req.body?.face_embedding
    );
    if (!embedding) {
      return res.status(400).json({ error: 'Request body must include an "embedding" array of numbers.' });
    }

    const matchCount = normalizeMatchLimit(req.body?.top_k ?? req.body?.limit, faceMatchDefaultLimit);

    try {
      const { data, error } = await supabase.rpc(faceMatchFn, {
        query_embedding: embedding,
        match_count: matchCount,
      });

      if (error) {
        console.error('[supabase] Face match RPC failed:', error);
        return res.status(500).json({ error: 'Failed to fetch face matches.' });
      }

      return res.status(200).json({ candidates: Array.isArray(data) ? data : [] });
    } catch (error) {
      console.error('[face-matches] Unexpected error:', error);
      return res.status(500).json({ error: 'Unexpected error while retrieving face matches.' });
    }
  });

  // Face match via base64 image (image_base64) -> embedding -> Supabase RPC
  router.post('/face-matches/upload', async (req, res) => {
    if (!faceMatchFn || faceMatchFn.toLowerCase() === 'disabled') {
      return res.status(503).json({ error: 'Face matching RPC not configured.' });
    }
    const imageBase64 = req.body?.image_base64 || req.body?.imageBase64;
    if (typeof imageBase64 !== 'string' || imageBase64.trim().length < 50) {
      return res.status(400).json({ error: 'image_base64 must be a valid base64-encoded image string.' });
    }
    const embeddingServiceUrl = process.env.EMBEDDING_SERVICE_URL;
    if (!embeddingServiceUrl) {
      return res.status(500).json({ error: 'EMBEDDING_SERVICE_URL not configured.' });
    }
    try {
      const fetch = (await import('node-fetch')).default; // dynamic import to avoid ESM issues
      const embedResp = await fetch(`${embeddingServiceUrl.replace(/\/$/, '')}/generate_embedding`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: imageBase64 }),
      });
      if (!embedResp.ok) {
        const text = await embedResp.text();
        return res.status(502).json({ error: 'Embedding service error', details: text });
      }
      const embedJson = await embedResp.json();
      const embedding = ensureEmbeddingArray(embedJson.embedding);
      if (!embedding) {
        return res.status(500).json({ error: 'Invalid embedding returned.' });
      }
      const limit = normalizeMatchLimit(req.body?.top_k ?? req.body?.limit, faceMatchDefaultLimit);
      const { data, error } = await supabase.rpc(faceMatchFn, {
        query_embedding: embedding,
        match_count: limit,
      });
      if (error) {
        console.error('[supabase] Face match RPC failed:', error);
        return res.status(500).json({ error: 'Failed to fetch face matches.' });
      }
      return res.json({ candidates: Array.isArray(data) ? data : [], faces_detected: embedJson.faces_detected });
    } catch (e) {
      console.error('[face-matches/upload] Unexpected error', e);
      return res.status(500).json({ error: 'Unexpected error during face match upload.' });
    }
  });

  // Simplified emergency submission endpoint
  router.post('/emergencies', async (req, res) => {
    if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
      return res.status(400).json({ error: 'Request body must be a JSON object.' });
    }
    const rawPayload = clonePayload(req.body);
    const description = typeof rawPayload.description === 'string' ? rawPayload.description.trim() : '';
    if (!description) {
      return res.status(400).json({ error: 'description is required' });
    }
    const timestamp = new Date().toISOString();
    const insertRecord = {
      source: 'app',
      sender_number: null,
      timestamp,
      message: description,
      audio_url: null,
      media_urls: [],
      location: null,
      raw_data: rawPayload, // description already embedded here
      // Allow client to optionally supply a precomputed victim face embedding array
      ...(Array.isArray(req.body?.victim_face_embedding) && req.body.victim_face_embedding.length > 0
        ? { victim_face_embedding: req.body.victim_face_embedding.map(Number).filter((n) => !Number.isNaN(n)) }
        : {}),
    };
    try {
      const { data: inserted, error: supabaseError } = await supabase
        .from('emergencies')
        .insert([insertRecord])
        .select()
        .single();
      if (supabaseError) {
        console.error('[supabase] Failed to persist emergency payload:', supabaseError);
        return res.status(500).json({ error: 'Failed to persist emergency payload.' });
      }
      return res.status(201).json({ emergency_id: inserted?.id ?? null, raw_payload: rawPayload });
    } catch (error) {
      console.error('[emergencies] Unexpected error:', error);
      return res.status(500).json({ error: 'Unexpected error while processing emergency.' });
    }
  });

  return router;
}

module.exports = { createEmergencyRouter };
