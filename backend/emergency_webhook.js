'use strict';

const express = require('express');
const twilio = require('twilio');
const { createClient } = require('@supabase/supabase-js');

const DEFAULT_TRANSCRIPTION_ATTEMPTS = 6;
const TRANSCRIPTION_POLL_INTERVAL_MS = 2000;

/**
 * Helper that sleeps for the given duration.
 * @param {number} ms
 * @returns {Promise<void>}
 */
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Attempt to fetch a completed transcription for the provided recording SID.
 * Falls back to null if transcription fails or times out.
 *
 * @param {import('twilio').Twilio} client
 * @param {string | undefined} recordingSid
 * @returns {Promise<string | null>}
 */
async function transcribeRecording(client, recordingSid) {
  if (!recordingSid) {
    return null;
  }

  try {
    // Kick off transcription generation (idempotent if it already exists).
    await client.transcriptions.create({ recordingSid }).catch(() => undefined);

    for (let attempt = 0; attempt < DEFAULT_TRANSCRIPTION_ATTEMPTS; attempt += 1) {
      const transcriptions = await client
        .recordings(recordingSid)
        .transcriptions.list({ limit: 1 });

      const transcription = transcriptions?.[0];
      if (!transcription) {
        await delay(TRANSCRIPTION_POLL_INTERVAL_MS);
        continue;
      }

      if (transcription.status === 'completed') {
        return transcription.transcriptionText ?? null;
      }

      if (transcription.status === 'failed') {
        console.warn(
          '[twilio] Transcription failed for recording %s: %s',
          recordingSid,
          transcription.errorText ?? transcription.status
        );
        return null;
      }

      await delay(TRANSCRIPTION_POLL_INTERVAL_MS);
    }

    console.warn(
      '[twilio] Transcription timed out for recording %s after %d attempts',
      recordingSid,
      DEFAULT_TRANSCRIPTION_ATTEMPTS
    );
    return null;
  } catch (error) {
    console.error('[twilio] Unable to transcribe recording %s: %s', recordingSid, error.message);
    return null;
  }
}

/**
 * Collect Twilio media URLs from the webhook body.
 * @param {Record<string, any>} body
 * @returns {string[]}
 */
function extractMediaUrls(body) {
  const mediaUrls = [];
  const numMedia = Number.parseInt(body.NumMedia ?? '0', 10);
  for (let index = 0; index < numMedia; index += 1) {
    const mediaUrl = body[`MediaUrl${index}`];
    if (mediaUrl) {
      mediaUrls.push(mediaUrl);
    }
  }
  return mediaUrls;
}

/**
 * Determine source channel from Twilio payload.
 * @param {Record<string, any>} body
 * @returns {'sms' | 'whatsapp' | 'voice'}
 */
function resolveSource(body) {
  if (body.CallSid || body.RecordingSid) {
    return 'voice';
  }
  if (typeof body.From === 'string' && body.From.startsWith('whatsapp:')) {
    return 'whatsapp';
  }
  return 'sms';
}

/**
 * Normalize the sender number (strip whatsapp prefix if present).
 * @param {Record<string, any>} body
 * @returns {string | null}
 */
function resolveSender(body) {
  const rawSender = body.From || body.Caller || body.WaId;
  if (!rawSender) {
    return null;
  }
  return String(rawSender).replace(/^whatsapp:/i, '');
}

/**
 * Derive a timestamp string from the payload or fallback to now.
 * @param {Record<string, any>} body
 * @returns {string}
 */
function resolveTimestamp(body) {
  const candidate =
    body.Timestamp || body.DateCreated || body.DateUpdated || body.DateSent || body.RecordingStartTime;
  const parsed = candidate ? new Date(candidate) : new Date();
  return parsed.toISOString();
}

/**
 * Extract latitude/longitude if provided.
 * @param {Record<string, any>} body
 * @returns {string | null}
 */
function resolveLocation(body) {
  const latitude = body.Latitude || body.lat || body.latitude;
  const longitude = body.Longitude || body.lon || body.longitude || body.lng;

  if (latitude && longitude) {
    return `${latitude}, ${longitude}`;
  }

  const location = body.Location || body.location;
  return location ? String(location) : null;
}

/**
 * Build an Express router that handles Twilio emergency webhooks.
 *
 * Expected environment variables:
 * - TWILIO_ACCOUNT_SID
 * - TWILIO_AUTH_TOKEN
 * - SUPABASE_URL
 * - SUPABASE_SERVICE_ROLE_KEY
 *
 * @param {object} [config]
 * @param {string} [config.supabaseUrl]
 * @param {string} [config.supabaseKey]
 * @param {string} [config.twilioAccountSid]
 * @param {string} [config.twilioAuthToken]
 * @returns {import('express').Router}
 */
function createEmergencyRouter(config = {}) {
  const router = express.Router();

  router.use(express.urlencoded({ extended: false }));
  router.use(express.json({ limit: '5mb' }));

  const supabaseUrl = config.supabaseUrl ?? process.env.SUPABASE_URL;
  const supabaseKey = config.supabaseKey ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  const twilioAccountSid = config.twilioAccountSid ?? process.env.TWILIO_ACCOUNT_SID;
  const twilioAuthToken = config.twilioAuthToken ?? process.env.TWILIO_AUTH_TOKEN;

  if (!supabaseUrl || !supabaseKey) {
    throw new Error('Supabase credentials are missing. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.');
  }
  if (!twilioAccountSid || !twilioAuthToken) {
    throw new Error('Twilio credentials are missing. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.');
  }

  const supabase = createClient(supabaseUrl, supabaseKey);
  const twilioClient = twilio(twilioAccountSid, twilioAuthToken);

  router.post('/twilio/emergency', async (req, res) => {
    try {
      const body = req.body || {};
      const source = resolveSource(body);
      const senderNumber = resolveSender(body);
      const timestamp = resolveTimestamp(body);
      const location = resolveLocation(body);
      const mediaUrls = extractMediaUrls(body);
      const audioUrl = body.RecordingUrl ? `${body.RecordingUrl}.mp3` : null;

      let rawMessage = body.Body || body.Message || null;
      if (source === 'voice') {
        const transcription = await transcribeRecording(twilioClient, body.RecordingSid);
        rawMessage = transcription || rawMessage;
      }

      if (!rawMessage && source !== 'voice') {
        return res.status(400).json({ error: 'Missing message body in Twilio payload.' });
      }

      const emergencyPayload = {
        source,
        sender_number: senderNumber,
        timestamp,
        raw_message: rawMessage,
        audio_url: audioUrl,
        media_urls: mediaUrls.length ? mediaUrls : undefined,
        location: location || undefined,
      };

      // Persist the structured payload for auditing and downstream processing.
      const { error: supabaseError } = await supabase.from('emergencies').insert([
        {
          source: emergencyPayload.source,
          sender_number: emergencyPayload.sender_number,
          timestamp: emergencyPayload.timestamp,
          message: emergencyPayload.raw_message,
          audio_url: emergencyPayload.audio_url,
          media_urls: emergencyPayload.media_urls ?? [],
          location: emergencyPayload.location ?? null,
          raw_data: emergencyPayload,
        },
      ]);

      if (supabaseError) {
        console.error('[supabase] Failed to insert emergency record:', supabaseError);
        return res.status(500).json({ error: 'Failed to persist emergency payload.' });
      }

      return res.status(200).json(emergencyPayload);
    } catch (error) {
      console.error('[webhook] Unexpected error handling Twilio webhook:', error);
      return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
  });

  return router;
}

module.exports = { createEmergencyRouter };
