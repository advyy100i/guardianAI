import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'auth_service.dart';

final supabaseClientProvider = Provider<SupabaseClient>((ref) {
  return Supabase.instance.client;
});

final authStateStreamProvider = StreamProvider<AuthState>((ref) {
  final client = ref.watch(supabaseClientProvider);
  return client.auth.onAuthStateChange;
});

final sessionProvider = Provider<AsyncValue<Session?>>((ref) {
  return ref.watch(authStateStreamProvider).whenData((event) => event.session);
});

final currentUserProvider = Provider<AsyncValue<User?>>((ref) {
  return ref.watch(sessionProvider).whenData((session) => session?.user);
});

final authServiceProvider = Provider<AuthService>((ref) {
  final client = ref.watch(supabaseClientProvider);
  return AuthService(client);
});
