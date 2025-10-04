import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:http/http.dart' as http;

class EmbeddingService {
  EmbeddingService({http.Client? httpClient})
    : _client = httpClient ?? http.Client();

  final http.Client _client;

  Uri get _endpoint {
    final endpoint = dotenv.env['EMBEDDING_SERVICE_URL'];
    if (endpoint == null || endpoint.isEmpty) {
      throw StateError(
        'Missing EMBEDDING_SERVICE_URL in .env. Set the DeepFace embedding service endpoint.',
      );
    }
    return Uri.parse(endpoint);
  }

  Future<List<double>> generateEmbedding(Uint8List imageBytes) async {
    final endpoint = _endpoint;

    late final http.Response response;
    try {
      response = await _client.post(
        endpoint,
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode({'image_base64': base64Encode(imageBytes)}),
      );
    } on http.ClientException catch (error) {
      throw Exception(
        'Unable to reach embedding service at ${endpoint.toString()}: ${error.message}. '
        'Ensure the DeepFace microservice is running and accessible from this device.',
      );
    } catch (error) {
      throw Exception(
        'Failed to call embedding service at ${endpoint.toString()}: $error',
      );
    }

    if (response.statusCode != 200) {
      throw Exception('Embedding service error: HTTP ${response.statusCode}');
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    final embeddingRaw = decoded['embedding'];
    if (embeddingRaw is! List) {
      throw const FormatException(
        'Embedding service response missing "embedding" list',
      );
    }

    return embeddingRaw
        .map(
          (value) =>
              value is num ? value.toDouble() : double.parse(value.toString()),
        )
        .toList(growable: false);
  }

  void dispose() {
    _client.close();
  }
}
