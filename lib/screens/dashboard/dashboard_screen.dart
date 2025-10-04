import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../services/auth/auth_providers.dart';
import '../capture/face_capture_screen.dart';
import '../emergency/emergency_report_screen.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(currentUserProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('GuardianAI Dashboard'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            onPressed: () async {
              await ref.read(authServiceProvider).signOut();
            },
            icon: const Icon(Icons.exit_to_app),
          ),
        ],
      ),
      body: userAsync.when(
        data: (user) {
          if (user == null) {
            return const Center(child: Text('No active session'));
          }
          return Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Welcome, ${user.email ?? 'guardian'}',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 16),
                Text(
                  'This dashboard will surface emergency triggers and victim identification workflows.',
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
                const SizedBox(height: 32),
                Card(
                  elevation: 2,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Icon(
                              Icons.face_retouching_natural,
                              size: 32,
                              color: Theme.of(context).colorScheme.primary,
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                'Manage your face embedding',
                                style: Theme.of(context).textTheme.titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w600),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Capture or refresh your face embedding to enable rapid victim identification.',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            FilledButton.icon(
                              onPressed: () async {
                                final result = await Navigator.of(context).push(
                                  MaterialPageRoute<bool>(
                                    builder: (_) => const FaceCaptureScreen(),
                                  ),
                                );

                                if (result == true && context.mounted) {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    const SnackBar(
                                      content: Text(
                                        'Face embedding updated successfully.',
                                      ),
                                    ),
                                  );
                                }
                              },
                              icon: const Icon(Icons.camera_alt_outlined),
                              label: const Text('Capture face now'),
                            ),
                            const SizedBox(width: 12),
                            OutlinedButton.icon(
                              onPressed: () {
                                showDialog<void>(
                                  context: context,
                                  builder: (dialogContext) => AlertDialog(
                                    title: const Text('Why capture your face?'),
                                    content: const Text(
                                      'GuardianAI uses face embeddings to quickly identify possible victims during emergencies. '
                                      'Keeping your embedding up to date ensures higher accuracy when responders search for you.',
                                    ),
                                    actions: [
                                      TextButton(
                                        onPressed: () =>
                                            Navigator.of(dialogContext).pop(),
                                        child: const Text('Got it'),
                                      ),
                                    ],
                                  ),
                                );
                              },
                              icon: const Icon(Icons.info_outline),
                              label: const Text('Why it matters'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 24),
                Card(
                  elevation: 2,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Icon(
                              Icons.emergency_share_outlined,
                              size: 32,
                              color: Theme.of(context).colorScheme.error,
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                'Report an emergency',
                                style: Theme.of(context).textTheme.titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w600),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Create a manual emergency report to alert responders and store the incident in GuardianAI.',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                        const SizedBox(height: 16),
                        FilledButton.icon(
                          onPressed: () async {
                            final result = await Navigator.of(context)
                                .push<bool>(
                                  MaterialPageRoute(
                                    builder: (_) =>
                                        const EmergencyReportScreen(),
                                  ),
                                );

                            if (result == true && context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text('Emergency report submitted.'),
                                ),
                              );
                            }
                          },
                          icon: const Icon(Icons.send_outlined),
                          label: const Text('Report now'),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          );
        },
        error: (error, _) =>
            Center(child: Text('Failed to load session: $error')),
        loading: () => const Center(child: CircularProgressIndicator()),
      ),
    );
  }
}
