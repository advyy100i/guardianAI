import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../services/auth/auth_providers.dart';
import 'login_screen.dart';

typedef AuthenticatedBuilder = Widget Function(BuildContext context);

typedef UnauthenticatedBuilder = Widget Function(BuildContext context);

class AuthGate extends HookConsumerWidget {
  const AuthGate({
    super.key,
    required this.authenticatedBuilder,
    this.unauthenticatedBuilder,
  });

  final AuthenticatedBuilder authenticatedBuilder;
  final UnauthenticatedBuilder? unauthenticatedBuilder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(currentUserProvider);

    return authState.when(
      data: (user) {
        if (user != null) {
          return authenticatedBuilder(context);
        }
        if (unauthenticatedBuilder != null) {
          return unauthenticatedBuilder!(context);
        }
        return const LoginScreen();
      },
      error: (error, stackTrace) => Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const CircularProgressIndicator(),
                const SizedBox(height: 24),
                Text(
                  'Authentication error: ${error.toString()}',
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      ),
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
    );
  }
}
