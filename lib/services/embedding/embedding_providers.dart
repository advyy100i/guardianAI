import 'package:hooks_riverpod/hooks_riverpod.dart';

import 'embedding_service.dart';

final embeddingServiceProvider = Provider<EmbeddingService>((ref) {
  final service = EmbeddingService();
  ref.onDispose(service.dispose);
  return service;
});
