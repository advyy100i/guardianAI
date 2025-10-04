import 'package:supabase_flutter/supabase_flutter.dart';

class ProfileService {
  ProfileService(this._client);

  final SupabaseClient _client;

  Future<void> upsertUserProfile({
    required User user,
    String? name,
    String? phone,
    Map<String, dynamic>? contacts,
    List<double>? faceEmbedding,
  }) async {
    final payload = <String, dynamic>{
      'id': user.id,
      'name': name ?? user.userMetadata?['full_name'],
      'phone': phone ?? user.userMetadata?['phone'],
      'contacts': contacts ?? user.userMetadata?['contacts'],
      if (faceEmbedding != null) 'face_embedding': faceEmbedding,
    };

    payload.removeWhere((_, value) => value == null);

    await _client.from('users').upsert(payload);
  }
}
