import 'package:hooks_riverpod/hooks_riverpod.dart';

import 'emergency_service.dart';

final emergencyServiceProvider = Provider.autoDispose<EmergencyService>((ref) {
  final service = EmergencyService();
  ref.onDispose(service.dispose);
  return service;
});

final emergencyReportControllerProvider =
    AutoDisposeStateNotifierProvider<
      EmergencyReportNotifier,
      AsyncValue<EmergencyReportResponse?>
    >((ref) {
      return EmergencyReportNotifier(ref);
    });

class EmergencyReportNotifier
    extends StateNotifier<AsyncValue<EmergencyReportResponse?>> {
  EmergencyReportNotifier(this._ref)
    : super(const AsyncValue<EmergencyReportResponse?>.data(null));

  final Ref _ref;

  Future<void> submitReport(EmergencyReportInput input) async {
    state = const AsyncValue.loading();
    try {
      final response = await _ref
          .read(emergencyServiceProvider)
          .submitEmergency(input);
      state = AsyncValue.data(response);
    } catch (error, stackTrace) {
      state = AsyncValue.error(error, stackTrace);
    }
  }

  void reset() {
    state = const AsyncValue<EmergencyReportResponse?>.data(null);
  }
}
