import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../services/auth/auth_providers.dart';
import '../../services/profile/profile_providers.dart';
import '../capture/face_capture_screen.dart';

class SignupScreen extends HookConsumerWidget {
  const SignupScreen({super.key});

  static const routeName = '/signup';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final nameController = useTextEditingController();
    final emailController = useTextEditingController();
    final phoneController = useTextEditingController();
    final passwordController = useTextEditingController();
    final confirmPasswordController = useTextEditingController();
    final isLoading = useState(false);

    Future<void> handleSignup() async {
      final name = nameController.text.trim();
      final email = emailController.text.trim();
      final phone = phoneController.text.trim();
      final password = passwordController.text;
      final confirmPassword = confirmPasswordController.text;
      final messenger = ScaffoldMessenger.of(context);

      if (name.isEmpty || email.isEmpty || password.isEmpty) {
        messenger.showSnackBar(
          const SnackBar(
            content: Text('Name, email, and password are required.'),
          ),
        );
        return;
      }

      if (password.length < 8) {
        messenger.showSnackBar(
          const SnackBar(
            content: Text('Password must be at least 8 characters.'),
          ),
        );
        return;
      }

      if (password != confirmPassword) {
        messenger.showSnackBar(
          const SnackBar(content: Text('Passwords do not match.')),
        );
        return;
      }

      try {
        isLoading.value = true;
        final appUser = await ref
            .read(authServiceProvider)
            .signUpWithEmail(
              email: email,
              password: password,
              fullName: name,
              phone: phone.isEmpty ? null : phone,
            );

        if (!context.mounted) return;

        if (appUser == null) {
          messenger.showSnackBar(
            const SnackBar(
              content: Text(
                'Check your email to verify the account before capturing your face.',
              ),
            ),
          );
          Navigator.of(context).popUntil((route) => route.isFirst);
          return;
        }

        final supabaseUser = Supabase.instance.client.auth.currentUser;
        if (supabaseUser != null) {
          await ref
              .read(profileServiceProvider)
              .upsertUserProfile(
                user: supabaseUser,
                name: name,
                phone: phone.isEmpty ? null : phone,
              );
          if (!context.mounted) return;
        }

        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute<void>(builder: (_) => const FaceCaptureScreen()),
          (route) => false,
        );
      } on AuthException catch (error) {
        if (!context.mounted) return;
        messenger.showSnackBar(SnackBar(content: Text(error.message)));
      } catch (error) {
        if (!context.mounted) return;
        messenger.showSnackBar(
          SnackBar(content: Text('Signup failed: $error')),
        );
      } finally {
        isLoading.value = false;
      }
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Create your GuardianAI account')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextFormField(
                      controller: nameController,
                      decoration: const InputDecoration(
                        labelText: 'Full name',
                        prefixIcon: Icon(Icons.person_outline),
                      ),
                      textCapitalization: TextCapitalization.words,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: emailController,
                      decoration: const InputDecoration(
                        labelText: 'Email',
                        prefixIcon: Icon(Icons.email_outlined),
                      ),
                      keyboardType: TextInputType.emailAddress,
                      autofillHints: const [AutofillHints.email],
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: phoneController,
                      decoration: const InputDecoration(
                        labelText: 'Phone (optional)',
                        prefixIcon: Icon(Icons.phone_outlined),
                      ),
                      keyboardType: TextInputType.phone,
                      autofillHints: const [AutofillHints.telephoneNumber],
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: passwordController,
                      decoration: const InputDecoration(
                        labelText: 'Password',
                        prefixIcon: Icon(Icons.lock_outline),
                      ),
                      obscureText: true,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: confirmPasswordController,
                      decoration: const InputDecoration(
                        labelText: 'Confirm password',
                        prefixIcon: Icon(Icons.lock_reset_outlined),
                      ),
                      obscureText: true,
                    ),
                    const SizedBox(height: 24),
                    FilledButton.icon(
                      onPressed: isLoading.value ? null : handleSignup,
                      icon: isLoading.value
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.verified_user_outlined),
                      label: Text(
                        isLoading.value
                            ? 'Creating account…'
                            : 'Create account',
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextButton(
                      onPressed: Navigator.of(context).maybePop,
                      child: const Text('Already have an account? Sign in'),
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
