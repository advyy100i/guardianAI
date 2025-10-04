import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../services/auth/auth_providers.dart';
import '../../services/profile/profile_providers.dart';
import 'signup_screen.dart';

class LoginScreen extends HookConsumerWidget {
  const LoginScreen({super.key});

  static const routeName = '/login';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final emailController = useTextEditingController();
    final passwordController = useTextEditingController();
    final isLoading = useState(false);

    Future<void> handleLogin() async {
      final email = emailController.text.trim();
      final password = passwordController.text;
      final messenger = ScaffoldMessenger.of(context);

      if (email.isEmpty || password.isEmpty) {
        messenger.showSnackBar(
          const SnackBar(content: Text('Email and password are required.')),
        );
        return;
      }

      try {
        isLoading.value = true;
        final appUser = await ref
            .read(authServiceProvider)
            .signInWithEmail(email: email, password: password);

        if (!context.mounted) return;

        final supabaseUser = Supabase.instance.client.auth.currentUser;
        if (supabaseUser != null) {
          await ref
              .read(profileServiceProvider)
              .upsertUserProfile(
                user: supabaseUser,
                name: appUser?.fullName,
                phone: appUser?.phone,
              );
        }
      } on AuthException catch (error) {
        if (!context.mounted) return;
        messenger.showSnackBar(SnackBar(content: Text(error.message)));
      } catch (error) {
        if (!context.mounted) return;
        messenger.showSnackBar(SnackBar(content: Text('Login failed: $error')));
      } finally {
        isLoading.value = false;
      }
    }

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
              child: Form(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Text(
                      'Welcome back',
                      style: TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Sign in with your registered GuardianAI email to continue.',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 32),
                    TextFormField(
                      controller: emailController,
                      decoration: const InputDecoration(
                        labelText: 'Email',
                        prefixIcon: Icon(Icons.email_outlined),
                      ),
                      keyboardType: TextInputType.emailAddress,
                      autofillHints: const [AutofillHints.username],
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: passwordController,
                      decoration: const InputDecoration(
                        labelText: 'Password',
                        prefixIcon: Icon(Icons.lock_outline),
                      ),
                      obscureText: true,
                      autofillHints: const [AutofillHints.password],
                    ),
                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: isLoading.value ? null : handleLogin,
                      child: isLoading.value
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Sign In'),
                    ),
                    const SizedBox(height: 12),
                    TextButton(
                      onPressed: () {
                        Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (context) => const SignupScreen(),
                          ),
                        );
                      },
                      child: const Text("Don't have an account? Create one"),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
