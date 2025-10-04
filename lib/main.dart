import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import 'core/app.dart';
import 'core/bootstrap.dart';

Future<void> main() async {
  await bootstrap();
  runApp(const ProviderScope(child: GuardianAIApp()));
}
