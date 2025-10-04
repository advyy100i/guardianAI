import 'package:supabase_flutter/supabase_flutter.dart';

import '../../models/app_user.dart';

class AuthService {
  AuthService(this._client);

  final SupabaseClient _client;

  Future<AppUser?> signInWithEmail({
    required String email,
    required String password,
  }) async {
    final response = await _client.auth.signInWithPassword(
      email: email,
      password: password,
    );

    final sessionUser = response.user;
    if (sessionUser == null) {
      return null;
    }

    return AppUser.fromSupabaseUser(sessionUser);
  }

  Future<AppUser?> signUpWithEmail({
    required String email,
    required String password,
    required String fullName,
    String? phone,
  }) async {
    final response = await _client.auth.signUp(
      email: email,
      password: password,
      data: {
        'full_name': fullName,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
      },
    );

    final session = response.session;
    final sessionUser = session?.user;
    if (session == null || sessionUser == null) {
      return null;
    }

    return AppUser.fromSupabaseUser(sessionUser);
  }

  Future<void> signOut() async {
    await _client.auth.signOut();
  }
}
