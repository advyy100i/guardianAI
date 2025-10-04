import 'package:flutter/widgets.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

/// Loads environment configuration and initializes global services such as Supabase.
Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();

  await dotenv.load(fileName: '.env');
  final supabaseUrl = dotenv.env['SUPABASE_URL'];
  final supabaseAnonKey = dotenv.env['SUPABASE_ANON_KEY'];

  if (supabaseUrl == null || supabaseUrl.isEmpty) {
    throw StateError(
      'Missing SUPABASE_URL in .env. Create the file at project root and populate required keys.',
    );
  }

  if (supabaseAnonKey == null || supabaseAnonKey.isEmpty) {
    throw StateError(
      'Missing SUPABASE_ANON_KEY in .env. Create the file at project root and populate required keys.',
    );
  }

  await Supabase.initialize(
    url: supabaseUrl,
    anonKey: supabaseAnonKey,
    realtimeClientOptions: const RealtimeClientOptions(
      logLevel: RealtimeLogLevel.info,
    ),
  );
}
