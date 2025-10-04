import 'dart:convert';

import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:http/http.dart' as http;

class EmergencyReportInput {
  EmergencyReportInput({
    required this.message,
    required this.senderNumber,
    this.location,
    this.latitude,
    this.longitude,
    this.mediaUrl,
  });

  final String message;
  final String senderNumber;
  final String? location;
  final double? latitude;
  final double? longitude;
  final String? mediaUrl;

  Map<String, dynamic> toRequestPayload() {
    final payload = <String, dynamic>{
      'Body': message,
      'From': senderNumber,
      'Timestamp': DateTime.now().toUtc().toIso8601String(),
    };

    if (location != null && location!.isNotEmpty) {
      payload['Location'] = location;
    }

    if (latitude != null && longitude != null) {
      payload['Latitude'] = latitude;
      payload['Longitude'] = longitude;
    }

    if (mediaUrl != null && mediaUrl!.isNotEmpty) {
      payload['MediaUrl0'] = mediaUrl;
      payload['NumMedia'] = '1';
    }

    return payload;
  }
}

class EmergencyReportResponse {
  EmergencyReportResponse({
    required this.source,
    required this.senderNumber,
    required this.timestamp,
    required this.rawMessage,
    this.audioUrl,
    this.mediaUrls,
    this.location,
  });

  final String source;
  final String? senderNumber;
  final DateTime timestamp;
  final String? rawMessage;
  final String? audioUrl;
  final List<String>? mediaUrls;
  final String? location;

  factory EmergencyReportResponse.fromJson(Map<String, dynamic> json) {
    return EmergencyReportResponse(
      source: json['source'] as String? ?? 'unknown',
      senderNumber: json['sender_number'] as String?,
      timestamp:
          DateTime.tryParse(json['timestamp'] as String? ?? '') ??
          DateTime.now().toUtc(),
      rawMessage: json['raw_message'] as String?,
      audioUrl: json['audio_url'] as String?,
      mediaUrls: (json['media_urls'] as List?)?.cast<String>(),
      location: json['location'] as String?,
    );
  }
}

class EmergencyService {
  EmergencyService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  Uri get _endpoint {
    final url = dotenv.env['EMERGENCY_WEBHOOK_URL'];
    if (url == null || url.isEmpty) {
      throw StateError(
        'Missing EMERGENCY_WEBHOOK_URL in .env. Set it to the GuardianAI emergency webhook endpoint.',
      );
    }
    return Uri.parse(url);
  }

  Future<EmergencyReportResponse> submitEmergency(
    EmergencyReportInput input,
  ) async {
    final response = await _client.post(
      _endpoint,
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(input.toRequestPayload()),
    );

    if (response.statusCode != 200) {
      throw Exception(
        'Emergency service error: HTTP ${response.statusCode} ${response.reasonPhrase ?? ''}'
            .trim(),
      );
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    return EmergencyReportResponse.fromJson(decoded);
  }

  void dispose() {
    _client.close();
  }
}
