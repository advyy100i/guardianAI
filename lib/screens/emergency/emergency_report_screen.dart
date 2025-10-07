import 'dart:typed_data';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:image_picker/image_picker.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:mime/mime.dart';

import '../../services/emergency/emergency_providers.dart';
import '../../services/emergency/emergency_service.dart';

class EmergencyReportScreen extends HookConsumerWidget {
  const EmergencyReportScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final formKey = useMemoized(GlobalKey<FormState>.new);
    final messageController = useTextEditingController();
    final locationController = useTextEditingController();
    final latitudeController = useTextEditingController();
    final longitudeController = useTextEditingController();

    final imageBytes = useState<Uint8List?>(null);
    final imageMimeType = useState<String?>(null);
    final imageFileName = useState<String?>(null);

    final reportState = ref.watch(emergencyReportControllerProvider);
    // Track the last submitted emergency id and whether a victim has been linked
    final linkedEmergencyId = useState<dynamic>(null);
    final victimLinked = useState<bool>(false);

    Future<void> showMatchesDialog({
      required dynamic emergencyId,
      required List<FaceMatchCandidate> matches,
    }) async {
      if (matches.isEmpty) {
        if (!context.mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No similar faces found.')),
        );
        return;
      }
      if (!context.mounted) return;
      await showModalBottomSheet(
        context: context,
        isScrollControlled: true,
        builder: (ctx) {
          return SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Select Matched User',
                    style: Theme.of(ctx).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 12),
                  ...matches.map(
                    (m) => ListTile(
                      title: Text(m.metadata['name']?.toString() ?? 'Unknown'),
                      subtitle: Text(
                        'Similarity: ${(m.score * 100).toStringAsFixed(2)}%',
                      ),
                      onTap: () async {
                        final service = ref.read(emergencyServiceProvider);
                        await service.updateEmergencyVictim(
                          emergencyId,
                          m.id.toString(),
                        );
                        if (ctx.mounted) Navigator.of(ctx).pop();
                        if (context.mounted) {
                          linkedEmergencyId.value = emergencyId;
                          victimLinked.value = true;
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text(
                                'Victim linked. Tap the summary button to view severity.',
                              ),
                            ),
                          );
                        }
                      },
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
              ),
            ),
          );
        },
      );
    }

    ref.listen<AsyncValue<EmergencyReportResponse?>>(
      emergencyReportControllerProvider,
      (previous, next) => next.whenOrNull(
        data: (resp) async {
          if (resp == null || !context.mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Emergency reported successfully. Link a victim to enable summary.',
              ),
            ),
          );
          // If image present (and embedding likely precomputed), attempt similar matches
          if (imageBytes.value != null) {
            try {
              final service = ref.read(emergencyServiceProvider);
              // Show lightweight progress indicator while processing face match.
              if (context.mounted) {
                showDialog(
                  context: context,
                  barrierDismissible: false,
                  builder: (_) =>
                      const Center(child: CircularProgressIndicator()),
                );
              }
              List<double> embedding = resp.victimFaceEmbedding ?? [];
              if (embedding.isEmpty) {
                try {
                  embedding = await service.generateEmbeddingFromImage(
                    imageBytes.value!,
                  );
                } finally {
                  if (context.mounted) {
                    Navigator.of(context, rootNavigator: true).pop();
                  }
                }
              } else {
                // Embedding already generated before insert; dismiss progress immediately.
                if (context.mounted) {
                  Navigator.of(context, rootNavigator: true).pop();
                }
              }
              // Fetch matches (no dialog for this minor network call; could extend if slow).
              final matchesRaw = await service.matchFaceFromEmbedding(
                embedding,
                limit: 5,
              );
              // Apply a simple similarity threshold if scores look like cosine similarity (0-1). Keep those >= 0.35.
              final matches = matchesRaw
                  .where((m) => m.score >= 0.35)
                  .toList(growable: false);
              await showMatchesDialog(
                emergencyId: resp.emergencyId,
                matches: matches,
              );
            } catch (e) {
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Face match failed: $e')),
                );
              }
            }
          }
        },
        error: (err, _) {
          if (!context.mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Failed to report emergency: $err')),
          );
        },
      ),
    );

    Future<void> handleSubmit() async {
      final messenger = ScaffoldMessenger.of(context);
      if (!(formKey.currentState?.validate() ?? false)) {
        messenger.showSnackBar(
          const SnackBar(content: Text('Please fill the required fields.')),
        );
        return;
      }
      final description = messageController.text.trim();
      final loc = locationController.text.trim();
      final lat = double.tryParse(latitudeController.text.trim());
      final lng = double.tryParse(longitudeController.text.trim());

      final input = EmergencyReportInput(
        description: description,
        location: loc.isEmpty ? null : loc,
        latitude: lat,
        longitude: lng,
        imageBytes: imageBytes.value,
        imageMimeType: imageMimeType.value,
        imageFileName: imageFileName.value,
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
                    'Describe the emergency. The information will be stored as raw JSON.',
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                  const SizedBox(height: 24),
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
                      helperText: 'Free-form address or coordinates.',
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
                  const SizedBox(height: 24),
                  Text(
                    'Attach photo (optional)',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      ElevatedButton.icon(
                        onPressed: isLoading
                            ? null
                            : () async {
                                final picker = ImagePicker();
                                final selected = await picker.pickImage(
                                  source: ImageSource.gallery,
                                  imageQuality: 85,
                                );
                                if (selected == null) return;
                                final bytes = await selected.readAsBytes();
                                imageBytes.value = bytes;
                                imageFileName.value = selected.name;
                                imageMimeType.value = lookupMimeType(
                                  selected.path,
                                );
                              },
                        icon: const Icon(Icons.upload_outlined),
                        label: Text(
                          imageBytes.value == null
                              ? 'Choose image'
                              : 'Replace image',
                        ),
                      ),
                      const SizedBox(width: 12),
                      if (imageBytes.value != null)
                        IconButton(
                          tooltip: 'Remove image',
                          onPressed: isLoading
                              ? null
                              : () {
                                  imageBytes.value = null;
                                  imageMimeType.value = null;
                                  imageFileName.value = null;
                                },
                          icon: const Icon(Icons.delete_outline),
                        ),
                    ],
                  ),
                  if (imageBytes.value != null) ...[
                    const SizedBox(height: 12),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: Image.memory(
                        imageBytes.value!,
                        height: 160,
                        width: double.infinity,
                        fit: BoxFit.cover,
                      ),
                    ),
                    if (imageFileName.value != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(
                          '${imageFileName.value} (${imageMimeType.value ?? 'image'})',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ),
                  ],
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
      floatingActionButton:
          (linkedEmergencyId.value != null && victimLinked.value)
          ? FloatingActionButton.extended(
              onPressed: () async {
                final service = ref.read(emergencyServiceProvider);
                showDialog(
                  context: context,
                  barrierDismissible: false,
                  builder: (_) =>
                      const Center(child: CircularProgressIndicator()),
                );
                Map<String, dynamic>? row;
                // Light polling: up to 2s while user explicitly waits
                for (var i = 0; i < 4; i++) {
                  row = await service.fetchEmergencySummary(
                    linkedEmergencyId.value,
                  );
                  if (row != null &&
                      (row['severity_score'] != null ||
                          row['summary_data'] != null)) {
                    break;
                  }
                  await Future.delayed(const Duration(milliseconds: 500));
                }
                if (context.mounted) {
                  Navigator.of(context, rootNavigator: true).pop();
                }
                if (!context.mounted) return;
                if (row != null &&
                    (row['severity_score'] != null ||
                        row['summary_data'] != null)) {
                  _showSummaryDialog(context, row);
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'Summary not ready yet. Try again shortly.',
                      ),
                    ),
                  );
                }
              },
              icon: const Icon(Icons.analytics_outlined),
              label: const Text('View Summary'),
            )
          : null,
    );
  }
}

void _showSummaryDialog(BuildContext context, Map<String, dynamic> row) {
  final scoreRaw = row['severity_score'];
  double? score;
  if (scoreRaw is num) score = scoreRaw.toDouble();
  final summary = row['summary_data'];
  String category = 'Unknown';
  if (summary is Map<String, dynamic>) {
    final c = summary['category'] ?? summary['severity_category'];
    if (c is String && c.isNotEmpty) category = c;
  }
  Color badgeColor;
  switch (category.toLowerCase()) {
    case 'critical':
      badgeColor = Colors.red.shade600;
      break;
    case 'urgent':
      badgeColor = Colors.orange.shade600;
      break;
    case 'non-urgent':
    case 'nonurgent':
      badgeColor = Colors.green.shade600;
      break;
    default:
      badgeColor = Theme.of(context).colorScheme.primary;
  }
  showDialog(
    context: context,
    builder: (dCtx) {
      return AlertDialog(
        title: Row(
          children: [
            Expanded(child: Text('Emergency Summary')),
            if (category.isNotEmpty)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: badgeColor.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: badgeColor),
                ),
                child: Text(
                  category.toUpperCase(),
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: badgeColor,
                    letterSpacing: 0.5,
                  ),
                ),
              ),
          ],
        ),
        content: SizedBox(
          width: 480,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (score != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: RichText(
                      text: TextSpan(
                        style: Theme.of(context).textTheme.bodyMedium,
                        children: [
                          const TextSpan(text: 'Severity score: '),
                          TextSpan(
                            text: score.toStringAsFixed(2),
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: badgeColor,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (summary != null)
                  _SummaryPrettyJsonView(data: summary as Map<String, dynamic>),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dCtx).pop(),
            child: const Text('Close'),
          ),
        ],
      );
    },
  );
}

class _SummaryPrettyJsonView extends StatelessWidget {
  const _SummaryPrettyJsonView({required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    // We pretty print but also highlight some top-level keys if present
    final encoder = const JsonEncoder.withIndent('  ');
    final text = encoder.convert(data);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceVariant.withOpacity(0.5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: Theme.of(context).dividerColor.withOpacity(0.4),
        ),
      ),
      child: SelectableText(
        text,
        style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
      ),
    );
  }
}
