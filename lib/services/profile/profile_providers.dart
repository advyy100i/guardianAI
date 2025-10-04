import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../auth/auth_providers.dart';
import 'profile_service.dart';

final profileServiceProvider = Provider<ProfileService>((ref) {
  final client = ref.watch(supabaseClientProvider);
  return ProfileService(client);
});
