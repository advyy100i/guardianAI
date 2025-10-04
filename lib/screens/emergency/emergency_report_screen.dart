import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../services/auth/auth_providers.dart';
import '../../services/emergency/emergency_providers.dart';
import '../../services/emergency/emergency_service.dart';

class EmergencyReportScreen extends HookConsumerWidget {
  const EmergencyReportScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final supabaseUser = ref.watch(currentUserProvider).value;
    final formKey = useMemoized(GlobalKey<FormState>.new);
    final messageController = useTextEditingController();
    final phoneController = useTextEditingController(text: supabaseUser?.phone);
    final locationController = useTextEditingController();
    final latitudeController = useTextEditingController();
    final longitudeController = useTextEditingController();
    final mediaUrlController = useTextEditingController();

    final reportState = ref.watch(emergencyReportControllerProvider);

    ref.listen<AsyncValue<EmergencyReportResponse?>>(
      emergencyReportControllerProvider,
      (previous, next) {
        next.whenOrNull(
          data: (response) {
            if (response == null) {
              return;
            }

            if (!context.mounted) {
              return;
            }

            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Emergency reported successfully.')),
            );
            Navigator.of(context).pop(true);
          },
          error: (error, _) {
            if (!context.mounted) {
              return;
            }
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Failed to report emergency: $error')),
            );
          },
        );
      },
    );

    Future<void> handleSubmit() async {
      final messenger = ScaffoldMessenger.of(context);
      if (!(formKey.currentState?.validate() ?? false)) {
        messenger.showSnackBar(
          const SnackBar(content: Text('Please fill the required fields.')),
        );
        return;
      }

      final message = messageController.text.trim();
      final sender = phoneController.text.trim();
      final mediaUrl = mediaUrlController.text.trim();
      final location = locationController.text.trim();
      final latitude = double.tryParse(latitudeController.text.trim());
      final longitude = double.tryParse(longitudeController.text.trim());

      final input = EmergencyReportInput(
        message: message,
        senderNumber: sender,
        location: location.isEmpty ? null : location,
        latitude: latitude,
        longitude: longitude,
        mediaUrl: mediaUrl.isEmpty ? null : mediaUrl,
      );

      await ref
          .read(emergencyReportControllerProvider.notifier)
          .submitReport(input);
    }

    final isLoading = reportState.isLoading;

    return Scaffold(
      appBar: AppBar(title: const Text('Report emergency')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Form(
              key: formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Share details about the emergency so GuardianAI can act quickly.',
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                  const SizedBox(height: 24),
                  TextFormField(
                    controller: phoneController,
                    decoration: const InputDecoration(
                      labelText: 'Contact number',
                      prefixIcon: Icon(Icons.phone_outlined),
                      helperText: 'Include country code (e.g., +1...).',
                    ),
                    keyboardType: TextInputType.phone,
                    validator: (value) {
                      if (value == null || value.trim().isEmpty) {
                        return 'Contact number is required.';
                      }
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: messageController,
                    decoration: const InputDecoration(
                      labelText: 'Emergency description',
                      prefixIcon: Icon(Icons.report_gmailerrorred_outlined),
                      alignLabelWithHint: true,
                    ),
                    maxLines: 5,
                    validator: (value) {
                      if (value == null || value.trim().isEmpty) {
                        return 'Please describe the emergency.';
                      }
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: locationController,
                    decoration: const InputDecoration(
                      labelText: 'Location (optional)',
                      prefixIcon: Icon(Icons.place_outlined),
                      helperText:
                          'Free-form address or coordinates (will be stored as-is).',
                    ),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: TextFormField(
                          controller: latitudeController,
                          decoration: const InputDecoration(
                            labelText: 'Latitude (optional)',
                          ),
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextFormField(
                          controller: longitudeController,
                          decoration: const InputDecoration(
                            labelText: 'Longitude (optional)',
                          ),
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: mediaUrlController,
                    decoration: const InputDecoration(
                      labelText: 'Photo URL (optional)',
                      prefixIcon: Icon(Icons.link_outlined),
                      helperText:
                          'Provide an accessible URL to any relevant photo or media.',
                    ),
                  ),
                  const SizedBox(height: 32),
                  FilledButton.icon(
                    onPressed: isLoading ? null : handleSubmit,
                    icon: isLoading
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.send_outlined),
                    label: Text(isLoading ? 'Submitting…' : 'Submit emergency'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
