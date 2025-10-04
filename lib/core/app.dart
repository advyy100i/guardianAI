import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../services/auth/auth_providers.dart';
import '../screens/auth/auth_gate.dart';
import '../screens/dashboard/dashboard_screen.dart';

class GuardianAIApp extends ConsumerWidget {
  const GuardianAIApp({super.key});

  static final _scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Warm up providers while building the app root.
  ref.watch(currentUserProvider);

    final theme = ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF4E73DF)),
      useMaterial3: true,
      visualDensity: VisualDensity.adaptivePlatformDensity,
    );

    return MaterialApp(
      title: 'GuardianAI',
      theme: theme,
      debugShowCheckedModeBanner: false,
      scaffoldMessengerKey: _scaffoldMessengerKey,
      home: AuthGate(
        authenticatedBuilder: (context) => const DashboardScreen(),
      ),
    );
  }
}
