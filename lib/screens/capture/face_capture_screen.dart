import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../services/auth/auth_providers.dart';
import '../../services/embedding/embedding_providers.dart';
import '../../services/profile/profile_providers.dart';

class FaceCaptureScreen extends HookConsumerWidget {
  const FaceCaptureScreen({super.key});

  static const routeName = '/capture/face';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useState<CameraController?>(null);
    final previewBytes = useState<Uint8List?>(null);
    final captureError = useState<String?>(null);
    final isProcessing = useState(false);
    final currentUser = ref.watch(currentUserProvider).value;
    final messenger = ScaffoldMessenger.of(context);

    useEffect(() {
      Future<void> initCamera() async {
        try {
          final cameras = await availableCameras();
          final frontCamera = cameras.firstWhere(
            (camera) => camera.lensDirection == CameraLensDirection.front,
            orElse: () => cameras.first,
          );

          final camController = CameraController(
            frontCamera,
            ResolutionPreset.medium,
            enableAudio: false,
            imageFormatGroup: ImageFormatGroup.jpeg,
          );

          await camController.initialize();
          controller.value = camController;
        } catch (error) {
          captureError.value = 'Unable to access camera: $error';
        }
      }

      initCamera();

      return () {
        controller.value?.dispose();
      };
    }, const []);

    Future<void> captureAndRegister() async {
      final camController = controller.value;
      final user = currentUser;
      if (camController == null || !camController.value.isInitialized) {
        messenger.showSnackBar(
          const SnackBar(content: Text('Camera not ready yet. Please wait.')),
        );
        return;
      }

      if (user == null) {
        messenger.showSnackBar(
          const SnackBar(
            content: Text('User session missing. Please sign in again.'),
          ),
        );
        return;
      }

      try {
        isProcessing.value = true;
        captureError.value = null;
        final file = await camController.takePicture();
        final bytes = await file.readAsBytes();
        previewBytes.value = bytes;

        final embedding = await ref
            .read(embeddingServiceProvider)
            .generateEmbedding(bytes);
        await ref
            .read(profileServiceProvider)
            .upsertUserProfile(user: user, faceEmbedding: embedding);

        if (!context.mounted) return;

        messenger.showSnackBar(
          const SnackBar(content: Text('Face registered successfully!')),
        );

        Navigator.of(context).pop(true);
      } catch (error) {
        captureError.value = 'Failed to process image: $error';
        messenger.showSnackBar(
          SnackBar(content: Text('Failed to register face: $error')),
        );
      } finally {
        isProcessing.value = false;
      }
    }

    Widget buildPreview() {
      if (captureError.value != null) {
        return Center(
          child: Text(
            captureError.value!,
            style: const TextStyle(color: Colors.red),
            textAlign: TextAlign.center,
          ),
        );
      }

      final camController = controller.value;
      if (camController == null || !camController.value.isInitialized) {
        return const Center(child: CircularProgressIndicator());
      }

      return AspectRatio(
        aspectRatio: camController.value.aspectRatio,
        child: CameraPreview(camController),
      );
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Register your face')),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: buildPreview(),
                ),
              ),
            ),
            if (previewBytes.value != null)
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 8,
                ),
                child: SizedBox(
                  height: 120,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: Image.memory(previewBytes.value!, fit: BoxFit.cover),
                  ),
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: isProcessing.value
                          ? null
                          : () => Navigator.of(context).maybePop(false),
                      icon: const Icon(Icons.close),
                      label: const Text('Cancel'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: isProcessing.value ? null : captureAndRegister,
                      icon: isProcessing.value
                          ? const SizedBox(
                              height: 16,
                              width: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.camera_alt_outlined),
                      label: Text(
                        isProcessing.value
                            ? 'Processing…'
                            : 'Capture & register',
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
