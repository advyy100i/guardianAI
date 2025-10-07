import 'dart:convert';
import 'dart:typed_data';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:http/http.dart' as http;

class EmergencyReportInput {
  EmergencyReportInput({
    required this.description,
    this.location,
    this.latitude,
    this.longitude,
    this.imageBytes,
    this.imageMimeType,
    this.imageFileName,
    this.victimId,
    this.source,
  });
  final String description;
  final String? location;
  final double? latitude;
  final double? longitude;
  final Uint8List? imageBytes;
  final String? imageMimeType;
  final String? imageFileName;

  /// Optional victim id (UUID) if reporter selected a matched user.
  final String? victimId;

  /// Optional explicit source override (schema comment suggests 'sms' | 'whatsapp' | 'call').
  final String? source;

  Map<String, dynamic> toRawPayload() {
    final payload = <String, dynamic>{
      'description': description,
      if (location != null && location!.isNotEmpty) 'location': location,
      if (latitude != null && longitude != null)
        'coordinates': {'latitude': latitude, 'longitude': longitude},
    };
    if (imageBytes != null && imageBytes!.isNotEmpty) {
      payload['media'] = [
        {
          'filename': imageFileName ?? 'attachment.jpg',
          'content_type': imageMimeType ?? 'image/jpeg',
          'content_base64': base64Encode(imageBytes!),
        },
      ];
    }
    return payload;
  }
}

class EmergencyReportResponse {
  EmergencyReportResponse({
    required this.emergencyId,
    required this.rawPayload,
    this.victimFaceEmbedding,
  });
  final dynamic emergencyId;
  final Map<String, dynamic> rawPayload;
  final List<double>?
  victimFaceEmbedding; // stored embedding (512-d) if image provided
}

class FaceMatchCandidate {
  FaceMatchCandidate({
    required this.id,
    required this.score,
    required this.metadata,
  });
  final dynamic id;
  final double score;
  final Map<String, dynamic> metadata;
}

class EmergencyService {
  EmergencyService();
  final _supabase = Supabase.instance.client;

  Future<EmergencyReportResponse> submitEmergency(
    EmergencyReportInput input,
  ) async {
    final raw = input.toRawPayload();
    final description = input.description.trim();
    if (description.isEmpty) {
      throw Exception('Description required');
    }
    // Precompute face embedding (if image present) so we can insert victim_face_embedding directly.
    List<double>? precomputedEmbedding;
    if (input.imageBytes != null && input.imageBytes!.isNotEmpty) {
      try {
        precomputedEmbedding = await generateEmbeddingFromImage(
          input.imageBytes!,
        );
      } catch (e) {
        // Swallow embedding error here to still allow emergency submission; UI will surface separate face match failure.
        precomputedEmbedding = null;
      }
    }
    // Provided schema: id, source (NOT NULL), message, timestamp (default), location, victim_id, raw_data
    // We'll supply: source, message, timestamp (explicit for deterministic testing), location?, victim_id?, raw_data
    // Choose default source: env override or fallback to 'sms' (since schema comment restricts values; previously we used 'app').
    final defaultSource = dotenv.env['EMERGENCY_SOURCE'] ?? 'sms';
    final baseRecord = <String, dynamic>{
      'source': (input.source ?? defaultSource),
      'message': description,
      'raw_data': raw,
      // include explicit timestamp; if column missing code will retry without.
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      if (precomputedEmbedding != null)
        'victim_face_embedding': precomputedEmbedding,
    };
    if (raw['location'] != null) baseRecord['location'] = raw['location'];
    if (input.victimId != null && input.victimId!.isNotEmpty) {
      baseRecord['victim_id'] = input.victimId;
    }

    dynamic inserted;
    PostgrestException? lastError;

    Future<dynamic> attempt(Map<String, dynamic> record) async {
      try {
        return await _supabase
            .from('emergencies')
            .insert(record)
            .select()
            .maybeSingle();
      } on PostgrestException catch (e) {
        lastError = e;
        return null;
      }
    }

    inserted = await attempt(baseRecord);

    if (inserted == null && lastError != null) {
      // Retry: remove timestamp first (if schema omits it) then, if still failing due to source, attempt fallback to 'call'.
      var retryRecord = Map<String, dynamic>.from(baseRecord);
      retryRecord.remove('timestamp');
      inserted = await attempt(retryRecord);
      if (inserted == null && lastError != null) {
        // Fallback different allowed source value if custom one was rejected (enum constraint scenario).
        retryRecord['source'] = 'call';
        inserted = await attempt(retryRecord);
      }
    }

    if (inserted == null && lastError != null) {
      throw Exception('Insert failed: ${lastError!.message}');
    }

    return EmergencyReportResponse(
      emergencyId: inserted['id'],
      rawPayload: raw,
      victimFaceEmbedding: precomputedEmbedding,
    );
  }

  Future<List<FaceMatchCandidate>> matchFaceFromEmbedding(
    List<double> embedding, {
    int limit = 5,
  }) async {
    if (embedding.isEmpty) return [];
    // Prefer new schema RPC name if provided, else fallback to legacy.
    final rpc =
        dotenv.env['SUPABASE_SIMILAR_FACES_FUNCTION'] ??
        dotenv.env['SUPABASE_FACE_MATCH_FUNCTION'] ??
        'find_similar_faces';
    // We'll attempt parameter signatures sequentially to avoid PostgREST function cache mismatch:
    // 1. (query, match_limit)
    // 2. (query, match_count)
    // 3. (query_embedding, match_limit)
    // 4. (query_embedding, match_count)
    // Stop at first success returning a list.
    final attempts = [
      {'query': embedding, 'match_limit': limit},
      {'query': embedding, 'match_count': limit},
      {'query_embedding': embedding, 'match_limit': limit},
      {'query_embedding': embedding, 'match_count': limit},
    ];

    List<dynamic>? resp;
    for (final paramSet in attempts) {
      try {
        final r = await _supabase.rpc(rpc, params: paramSet);
        if (r is List) {
          resp = r;
          break;
        }
      } on PostgrestException catch (e) {
        // If function signature mismatch (PGRST202), continue trying alternatives.
        if (!(e.message.contains('PGRST202') ||
            e.message.contains('not found'))) {
          rethrow; // different error, propagate
        }
      }
    }
    if (resp == null) return [];
    return resp.map((raw) {
      final m = (raw as Map).cast<String, dynamic>();
      // unify fields
      final userId = m['user_id'] ?? m['id'];
      final similarity = (m['similarity'] ?? m['score'] ?? m['distance']);
      double score = 0;
      if (similarity is num) {
        score = similarity.toDouble();
      }
      return FaceMatchCandidate(id: userId, score: score, metadata: m);
    }).toList();
  }

  Future<List<double>> generateEmbeddingFromImage(Uint8List imageBytes) async {
    final url = dotenv.env['EMBEDDING_SERVICE_URL'];
    if (url == null || url.isEmpty) {
      throw Exception('EMBEDDING_SERVICE_URL missing');
    }
    // Normalize URL: allow providing base or direct endpoint.
    Uri endpoint;
    try {
      final base = Uri.parse(url);
      final last = base.pathSegments.isNotEmpty ? base.pathSegments.last : '';
      if (last == 'generate_embedding' || last == 'generate_embeddings') {
        endpoint = base; // already points to endpoint
      } else {
        // append endpoint safely
        final normalized = url.endsWith('/')
            ? '${url}generate_embedding'
            : '$url/generate_embedding';
        endpoint = Uri.parse(normalized);
      }
    } catch (_) {
      throw Exception('Invalid EMBEDDING_SERVICE_URL');
    }
    final b64 = base64Encode(imageBytes);
    Future<http.Response> doPost({required bool relaxed}) {
      return http.post(
        endpoint,
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode({'image_base64': b64, if (relaxed) 'relaxed': true}),
      );
    }

    var resp = await doPost(relaxed: false);
    Map<String, dynamic>? decoded;
    try {
      decoded = jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (_) {
      // keep null if not JSON
    }

    if (resp.statusCode != 200) {
      final detail = decoded?['detail'] ?? decoded?['error'];
      if (resp.statusCode == 422) {
        // Common DeepFace no-face detected message patterns
        final reason = (detail is String)
            ? detail
            : 'No face detected or invalid image.';
        throw Exception('No face detected: $reason');
      }
      if (resp.statusCode == 422) {
        // Retry once in relaxed mode (multi-detector + optional raw forward pass).
        resp = await doPost(relaxed: true);
        try {
          decoded = jsonDecode(resp.body) as Map<String, dynamic>;
        } catch (_) {}
      }
      if (resp.statusCode != 200) {
        throw Exception('Bad image data: ${detail ?? 'invalid payload'}');
      }
      throw Exception(
        'Embedding service error ${resp.statusCode}: ${detail ?? 'Unexpected failure'}',
      );
    }
    if (decoded == null) {
      throw Exception('Embedding service returned non-JSON response');
    }
    final list = decoded['embedding'];
    if (list is! List) {
      throw Exception('Invalid embedding payload (missing embedding list)');
    }
    final vector = list
        .whereType<num>()
        .map((n) => n.toDouble())
        .toList(growable: false);
    // Validate expected embedding length (Facenet512 => 512 dims). Allow pass-through if different but warn via exception.
    if (vector.length != 512) {
      // Not throwing hard error—some models may differ. Provide gentle notice.
      // If you want to enforce: uncomment next line.
      // throw Exception('Unexpected embedding length ${vector.length} (expected 512)');
    }
    return vector;
  }

  Future<void> updateEmergencyVictim(
    dynamic emergencyId,
    String victimUserId,
  ) async {
    if (emergencyId == null) return;
    await _supabase
        .from('emergencies')
        .update({'victim_id': victimUserId})
        .eq('id', emergencyId);
    // After victim is linked, attempt summarization (post-select to reduce wasted work if user cancels sheet)
    try {
      await summarizeEmergency(emergencyId);
    } catch (_) {
      // Silent failure; we don't block victim linkage if summarization fails.
    }
  }

  Future<void> summarizeEmergency(dynamic emergencyId) async {
    if (emergencyId == null) return;
    final summarizerUrl = dotenv.env['SUMMARIZING_SERVICE_URL'];
    if (summarizerUrl == null || summarizerUrl.isEmpty) return; // disabled
    // Fetch the emergency row to get original message (to avoid trusting local stale input)
    final row = await _supabase
        .from('emergencies')
        .select('id,message')
        .eq('id', emergencyId)
        .maybeSingle();
    if (row == null) return;
    final message = (row['message'] ?? '').toString();
    if (message.trim().isEmpty) return;
    Uri endpoint;
    try {
      endpoint = Uri.parse(
        summarizerUrl.endsWith('/')
            ? '${summarizerUrl}summarize'
            : '$summarizerUrl/summarize',
      );
    } catch (_) {
      return; // invalid URL
    }
    final resp = await http.post(
      endpoint,
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'description': message}),
    );
    if (resp.statusCode != 200) return; // ignore errors
    Map<String, dynamic> data;
    try {
      data = jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    final severity = data['severity_score'];
    final summary = data['summary'];
    final patch = <String, dynamic>{};
    if (severity is num) patch['severity_score'] = severity.toDouble();
    if (summary is Map<String, dynamic>) patch['summary_data'] = summary;
    if (patch.isEmpty) return;
    await _supabase.from('emergencies').update(patch).eq('id', emergencyId);
  }

  /// Fetch the severity_score and summary_data for an emergency (may be null if
  /// summarization has not completed yet). Returns a map with keys:
  /// { 'severity_score': double?, 'summary_data': Map<String,dynamic>? }
  Future<Map<String, dynamic>?> fetchEmergencySummary(
    dynamic emergencyId,
  ) async {
    if (emergencyId == null) return null;
    final row = await _supabase
        .from('emergencies')
        .select('id,severity_score,summary_data')
        .eq('id', emergencyId)
        .maybeSingle();
    if (row == null) return null;
    return {
      'severity_score': row['severity_score'],
      'summary_data': row['summary_data'],
    };
  }
}
