from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import paths


class AuthPatchTests(unittest.TestCase):
    def _reload_auth(self, tmpdir: str):
        users_path = os.path.join(tmpdir, "users.json")
        lockouts_path = os.path.join(tmpdir, "lockouts.json")
        limits_path = os.path.join(tmpdir, "account_creation_limits.json")
        stack = ExitStack()
        stack.enter_context(patch.object(paths, "users_file", return_value=users_path))
        stack.enter_context(patch.object(paths, "lockouts_file", return_value=lockouts_path))
        stack.enter_context(patch.object(paths, "account_creation_limits_file", return_value=limits_path))
        import auth

        module = importlib.reload(auth)
        self.addCleanup(stack.close)
        return module, users_path, lockouts_path, limits_path


    def _read_json_file(self, path: str):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _assert_users_file_is_envelope_v2(self, path: str) -> dict:
        import secure_storage

        envelope = self._read_json_file(path)
        self.assertEqual(envelope.get("storage_format_version"), secure_storage.STORAGE_FORMAT_VERSION)
        self.assertIs(envelope.get("encrypted"), True)
        self.assertEqual(envelope.get("algorithm"), secure_storage.ALGORITHM)
        self.assertEqual(envelope.get("key_id"), secure_storage.DEFAULT_KEY_ID)
        self.assertIsInstance(envelope.get("payload"), str)
        self.assertGreater(len(envelope.get("payload") or ""), 20)
        self.assertIsInstance(envelope.get("hmac"), str)
        self.assertEqual(len(envelope.get("hmac") or ""), 64)
        plaintext_fields = secure_storage.envelope_plaintext_fields(envelope)
        self.assertEqual(plaintext_fields, {})
        return envelope

    def _load_users_from_envelope(self, auth_module, path: str) -> dict:
        import secure_storage

        self._assert_users_file_is_envelope_v2(path)
        users, state = secure_storage.load_enveloped_json(
            path,
            {},
            coerce=auth_module._coerce_users_payload,
            rewrite_migrated=False,
        )
        self.assertEqual(state, "envelope_v2")
        return users

    def test_slugify_username_is_shared_and_stable(self) -> None:
        import auth
        from utils import identity

        self.assertIs(auth.slugify_username, identity.slugify_username)
        self.assertEqual(identity.slugify_username("  User.Name  "), "user.name")
        self.assertEqual(identity.slugify_username("User Name"), "user_name")
        self.assertEqual(identity.slugify_username("__Mixed---Value__"), "mixed---value")

    def test_lockout_persists_across_module_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, lockouts_path, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            created = auth.create_user("alice", "Password1234", "Alice")
            self.assertTrue(created["ok"])

            for _ in range(auth.MAX_LOGIN_FAILS):
                result = auth.verify_user("alice", "wrong-password")
                self.assertFalse(result["ok"])

            # Lockouts file now uses encrypted envelope (Phase 2: ISSUE-011).
            # Verify via the auth API rather than raw JSON inspection.
            self.assertTrue(os.path.exists(lockouts_path))

            # The encrypted envelope is NOT human-readable plaintext.
            with open(lockouts_path, encoding="utf-8") as handle:
                raw = json.load(handle)
            # Must be a Fernet envelope, not a plain dict with "alice" as a key.
            self.assertIn("encrypted", raw, "lockouts.json must be an encrypted envelope after Phase 2")
            self.assertTrue(raw.get("encrypted"), "lockouts.json encrypted flag must be True")
            self.assertNotIn("alice", raw, "alice key must not appear in plaintext of encrypted lockouts file")

            # Verify the lockout is still enforced after a module reload.
            auth_reloaded, _, _, _ = self._reload_auth(tmpdir)
            blocked = auth_reloaded.verify_user("alice", "Password1234")
            self.assertFalse(blocked["ok"])
            self.assertIn("Too many failed attempts", blocked["message"])

    def test_create_user_throttling_blocks_rapid_second_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 30
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            first = auth.create_user("user-one", "Password1234", "One")
            second = auth.create_user("user-two", "Password1234", "Two")

            self.assertTrue(first["ok"])
            self.assertFalse(second["ok"])
            self.assertIn("before creating another account", second["message"])

    def test_users_file_getter_is_lazy(self) -> None:
        import auth

        with tempfile.TemporaryDirectory() as tmpdir:
            path_a = os.path.join(tmpdir, "users_a.json")
            path_b = os.path.join(tmpdir, "users_b.json")
            limits_path = os.path.join(tmpdir, "limits.json")
            lockouts_path = os.path.join(tmpdir, "lockouts.json")

            with patch.object(auth, "users_file", return_value=path_a), patch.object(auth, "account_creation_limits_file", return_value=limits_path), patch.object(auth, "lockouts_file", return_value=lockouts_path):
                auth.CREATE_USER_COOLDOWN_SECONDS = 0
                auth.CREATE_USER_MAX_IN_WINDOW = 99
                created_a = auth.create_user("first-user", "Password1234", "A")
                self.assertTrue(created_a["ok"])

            with patch.object(auth, "users_file", return_value=path_b), patch.object(auth, "account_creation_limits_file", return_value=limits_path), patch.object(auth, "lockouts_file", return_value=lockouts_path):
                auth.CREATE_USER_COOLDOWN_SECONDS = 0
                auth.CREATE_USER_MAX_IN_WINDOW = 99
                created_b = auth.create_user("second-user", "Password1234", "B")
                self.assertTrue(created_b["ok"])

            users_a = self._load_users_from_envelope(auth, path_a)
            users_b = self._load_users_from_envelope(auth, path_b)

            self.assertIn("first-user", users_a)
            self.assertNotIn("second-user", users_a)
            self.assertIn("second-user", users_b)
            self.assertNotIn("first-user", users_b)

    def test_new_user_onboarding_flags_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            created = auth.create_user("alice", "Password1234", "Alice")
            self.assertTrue(created["ok"])
            self.assertTrue(created["user"]["onboarding_pending"])
            self.assertFalse(created["user"]["onboarding_do_not_show_again"])

            updated = auth.complete_user_onboarding("alice", do_not_show_again=True, skipped=False)
            self.assertIsNotNone(updated)
            self.assertFalse(updated["onboarding_pending"])
            self.assertTrue(updated["onboarding_do_not_show_again"])
            self.assertTrue(updated["onboarding_completed_at"])



    def test_create_user_stores_normalized_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            created = auth.create_user("alice", "Password1234", "Alice", "  ALICE@Example.COM  ", require_email=True)

            self.assertTrue(created["ok"])
            users = self._load_users_from_envelope(auth, users_path)
            self.assertEqual(users["alice"]["email"], "alice@example.com")

    def test_create_user_writes_encrypted_envelope_without_plaintext_sensitive_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            created = auth.create_user("alice", "Password1234", "Alice", "alice@example.com", require_email=True)

            self.assertTrue(created["ok"])
            envelope = self._assert_users_file_is_envelope_v2(users_path)
            self.assertNotIn("alice", envelope)
            raw_file = open(users_path, encoding="utf-8").read()
            self.assertNotIn("alice@example.com", raw_file)
            self.assertNotIn("Password1234", raw_file)
            self.assertNotIn(str(created.get("recovery_code") or ""), raw_file)
            users = self._load_users_from_envelope(auth, users_path)
            self.assertEqual(users["alice"]["email"], "alice@example.com")

    def test_create_user_rejects_duplicate_email_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            first = auth.create_user("alice", "Password1234", "Alice", "alice@example.com", require_email=True)
            second = auth.create_user("bob", "Password1234", "Bob", "ALICE@EXAMPLE.COM", require_email=True)

            self.assertTrue(first["ok"])
            self.assertFalse(second["ok"])
            self.assertEqual(second["message_key"], "auth_email_exists")

    def test_create_user_requires_email_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            created = auth.create_user("alice", "Password1234", "Alice", "   ", require_email=True)

            self.assertFalse(created["ok"])
            self.assertEqual(created["message_key"], "auth_email_required")

    def test_load_users_normalizes_legacy_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            legacy_users = {
                "legacy-user": {
                    "user_id": "legacy-user",
                    "display_name": "Legacy",
                    "username": "LegacyUser",
                    "email": "  LEGACY@Example.COM  ",
                    "password_salt": "",
                    "password_hash": "",
                    "created_at": "2026-01-01 00:00:00",
                    "last_login_at": None,
                    "profile_state": "new",
                    "onboarding_pending": False,
                    "onboarding_completed_at": None,
                    "onboarding_do_not_show_again": False,
                    "onboarding_skipped_at": None,
                    "onboarding_version": auth.NEW_USER_ONBOARDING_VERSION,
                }
            }
            with open(users_path, "w", encoding="utf-8") as handle:
                json.dump(legacy_users, handle, ensure_ascii=False, indent=2)

            loaded = auth._load_users()

            self.assertEqual(loaded["legacy-user"]["email"], "legacy@example.com")
            persisted = self._load_users_from_envelope(auth, users_path)
            self.assertEqual(persisted["legacy-user"]["email"], "legacy@example.com")

    def test_create_user_rejects_invalid_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            created = auth.create_user("alice", "Password1234", "Alice", "not-an-email", require_email=True)

            self.assertFalse(created["ok"])
            self.assertEqual(created["message_key"], "auth_invalid_email")

    def test_lookup_username_hint_returns_masked_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            created = auth.create_user("yaseen3", "Password1234", "Yaseen", "yaseen@example.com", require_email=True)
            self.assertTrue(created["ok"])

            result = auth.lookup_username_hint_by_email("  YASEEN@example.com  ")

            self.assertTrue(result["ok"])
            self.assertEqual(result["message_key"], "auth_username_hint_ready")
            self.assertEqual(result["hint"], "ya***n3")

    def test_lookup_username_hint_uses_generic_message_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            result = auth.lookup_username_hint_by_email("missing@example.com")

            self.assertFalse(result["ok"])
            self.assertEqual(result["message_key"], "auth_username_hint_unavailable")

    def test_lookup_username_hint_rejects_blank_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)

            result = auth.lookup_username_hint_by_email("   ")

            self.assertFalse(result["ok"])
            self.assertEqual(result["message_key"], "auth_username_hint_email_required")

    def test_lookup_username_hint_handles_legacy_duplicate_email_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            legacy_users = {
                "alpha": {
                    "user_id": "alpha",
                    "display_name": "Alpha",
                    "username": "alpha11",
                    "email": "shared@example.com",
                    "password_salt": "",
                    "password_hash": "",
                    "created_at": "2026-01-01 00:00:00",
                    "last_login_at": None,
                    "profile_state": "new",
                    "onboarding_pending": False,
                    "onboarding_completed_at": None,
                    "onboarding_do_not_show_again": False,
                    "onboarding_skipped_at": None,
                    "onboarding_version": auth.NEW_USER_ONBOARDING_VERSION,
                },
                "beta": {
                    "user_id": "beta",
                    "display_name": "Beta",
                    "username": "beta22",
                    "email": "shared@example.com",
                    "password_salt": "",
                    "password_hash": "",
                    "created_at": "2026-01-01 00:00:00",
                    "last_login_at": None,
                    "profile_state": "new",
                    "onboarding_pending": False,
                    "onboarding_completed_at": None,
                    "onboarding_do_not_show_again": False,
                    "onboarding_skipped_at": None,
                    "onboarding_version": auth.NEW_USER_ONBOARDING_VERSION,
                },
            }
            with open(users_path, "w", encoding="utf-8") as handle:
                json.dump(legacy_users, handle, ensure_ascii=False, indent=2)

            result = auth.lookup_username_hint_by_email("shared@example.com")

            self.assertFalse(result["ok"])
            self.assertEqual(result["message_key"], "auth_username_hint_unavailable")

    def test_reveal_username_returns_full_username_after_password_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            created = auth.create_user("yaseen3", "Password1234", "Yaseen", "yaseen@example.com", require_email=True)
            self.assertTrue(created["ok"])

            result = auth.reveal_username_by_email("YASEEN@example.com", "Password1234")

            self.assertTrue(result["ok"])
            self.assertEqual(result["message_key"], "auth_username_reveal_ready")
            self.assertEqual(result["username"], "yaseen3")

    def test_reveal_username_requires_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            auth.create_user("yaseen3", "Password1234", "Yaseen", "yaseen@example.com", require_email=True)

            result = auth.reveal_username_by_email("yaseen@example.com", "   ")

            self.assertFalse(result["ok"])
            self.assertEqual(result["message_key"], "auth_username_reveal_password_required")

    def test_reveal_username_uses_generic_message_when_password_is_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            auth.create_user("yaseen3", "Password1234", "Yaseen", "yaseen@example.com", require_email=True)

            result = auth.reveal_username_by_email("yaseen@example.com", "WrongPassword1234")

            self.assertFalse(result["ok"])
            self.assertEqual(result["message_key"], "auth_username_reveal_unavailable")

    def test_reveal_username_respects_existing_lockout_protection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            auth.create_user("yaseen3", "Password1234", "Yaseen", "yaseen@example.com", require_email=True)

            for _ in range(auth.MAX_LOGIN_FAILS):
                result = auth.reveal_username_by_email("yaseen@example.com", "WrongPassword1234")
                self.assertFalse(result["ok"])

            blocked = auth.reveal_username_by_email("yaseen@example.com", "Password1234")
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["message_key"], "auth_login_locked")


    def test_legacy_user_without_email_can_still_sign_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            salt = auth.secrets.token_bytes(16)
            legacy_users = {
                "legacy-user": {
                    "user_id": "legacy-user",
                    "display_name": "Legacy",
                    "username": "LegacyUser",
                    "password_salt": auth.base64.b64encode(salt).decode("ascii"),
                    "password_hash": auth._hash_password("Password1234", salt),
                    "created_at": "2026-01-01 00:00:00",
                    "last_login_at": None,
                    "profile_state": "new",
                    "onboarding_pending": False,
                    "onboarding_completed_at": None,
                    "onboarding_do_not_show_again": False,
                    "onboarding_skipped_at": None,
                    "onboarding_version": auth.NEW_USER_ONBOARDING_VERSION,
                }
            }
            with open(users_path, "w", encoding="utf-8") as handle:
                json.dump(legacy_users, handle, ensure_ascii=False, indent=2)

            result = auth.verify_user("legacy-user", "Password1234")

            self.assertTrue(result["ok"])
            self.assertEqual(result["user"]["username"], "LegacyUser")

    def test_lookup_username_hint_returns_hint_without_full_username(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            created = auth.create_user("yaseen3", "Password1234", "Yaseen", "yaseen@example.com", require_email=True)
            self.assertTrue(created["ok"])

            result = auth.lookup_username_hint_by_email("yaseen@example.com")

            self.assertTrue(result["ok"])
            self.assertEqual(result["hint"], "ya***n3")
            self.assertNotIn("username", result)
            self.assertNotIn("user", result)
            self.assertNotIn("yaseen3", result["message"])

    def test_reveal_username_does_not_change_login_state_or_touch_last_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            created = auth.create_user("yaseen3", "Password1234", "Yaseen", "yaseen@example.com", require_email=True)
            self.assertTrue(created["ok"])

            before = auth._load_users()["yaseen3"].get("last_login_at")
            result = auth.reveal_username_by_email("yaseen@example.com", "Password1234")
            after = auth._load_users()["yaseen3"].get("last_login_at")

            self.assertTrue(result["ok"])
            self.assertEqual(result["username"], "yaseen3")
            self.assertNotIn("user", result)
            self.assertNotIn("onboarding_required", result)
            self.assertIsNone(before)
            self.assertIsNone(after)
            persisted = self._load_users_from_envelope(auth, users_path)
            self.assertIsNone(persisted["yaseen3"].get("last_login_at"))

    def test_create_user_returns_password_recovery_code_and_ready_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99

            created = auth.create_user("alice", "Password1234", "Alice", "alice@example.com", require_email=True)

            self.assertTrue(created["ok"])
            self.assertTrue(created["user"]["password_recovery_ready"])
            recovery_code = str(created.get("recovery_code") or "")
            self.assertTrue(recovery_code)
            users = self._load_users_from_envelope(auth, users_path)
            self.assertIn("password_recovery", users["alice"])
            self.assertNotEqual(users["alice"]["password_recovery"].get("hash"), recovery_code)
            raw_file = open(users_path, encoding="utf-8").read()
            self.assertNotIn("alice@example.com", raw_file)
            self.assertNotIn("Password1234", raw_file)
            self.assertNotIn(recovery_code, raw_file)

    def test_verify_password_reset_recovery_accepts_email_or_username(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            created = auth.create_user("alice", "Password1234", "Alice", "alice@example.com", require_email=True)
            code = created["recovery_code"]

            by_email = auth.verify_password_reset_recovery("alice@example.com", code)
            by_username = auth.verify_password_reset_recovery("Alice", code)

            self.assertTrue(by_email["ok"])
            self.assertEqual(by_email["message_key"], "auth_password_reset_verified")
            self.assertTrue(by_username["ok"])

    def test_reset_password_with_recovery_rotates_code_and_updates_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            created = auth.create_user("alice", "Password1234", "Alice", "alice@example.com", require_email=True)
            original_code = created["recovery_code"]

            reset = auth.reset_password_with_recovery("alice@example.com", original_code, "NewPassword1234")

            self.assertTrue(reset["ok"])
            self.assertEqual(reset["message_key"], "auth_password_reset_success")
            new_code = reset.get("recovery_code")
            self.assertTrue(new_code)
            self.assertNotEqual(original_code, new_code)
            signin = auth.verify_user("alice", "NewPassword1234")
            self.assertTrue(signin["ok"])
            stale = auth.verify_password_reset_recovery("alice@example.com", original_code)
            self.assertFalse(stale["ok"])
            self.assertEqual(stale["message_key"], "auth_password_reset_unavailable")
            fresh = auth.verify_password_reset_recovery("alice@example.com", new_code)
            self.assertTrue(fresh["ok"])

    def test_reset_password_with_recovery_rejects_wrong_code_and_locks_after_repeated_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, _, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            auth.create_user("alice", "Password1234", "Alice", "alice@example.com", require_email=True)

            for _ in range(auth.MAX_RECOVERY_FAILS):
                result = auth.verify_password_reset_recovery("alice@example.com", "WRONG-CODE-0000")
                self.assertFalse(result["ok"])

            blocked = auth.verify_password_reset_recovery("alice@example.com", "WRONG-CODE-0000")
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["message_key"], "auth_password_reset_locked")

    def test_reset_password_with_recovery_handles_legacy_user_without_recovery_code_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            salt = auth.secrets.token_bytes(16)
            legacy_users = {
                "legacy-user": {
                    "user_id": "legacy-user",
                    "display_name": "Legacy",
                    "username": "LegacyUser",
                    "email": "legacy@example.com",
                    "password_salt": auth.base64.b64encode(salt).decode("ascii"),
                    "password_hash": auth._hash_password("Password1234", salt),
                    "created_at": "2026-01-01 00:00:00",
                    "last_login_at": None,
                    "profile_state": "new",
                    "onboarding_pending": False,
                    "onboarding_completed_at": None,
                    "onboarding_do_not_show_again": False,
                    "onboarding_skipped_at": None,
                    "onboarding_version": auth.NEW_USER_ONBOARDING_VERSION,
                }
            }
            with open(users_path, "w", encoding="utf-8") as handle:
                json.dump(legacy_users, handle, ensure_ascii=False, indent=2)

            check = auth.verify_password_reset_recovery("legacy-user", "ANY-CODE")
            reset = auth.reset_password_with_recovery("legacy-user", "ANY-CODE", "NewPassword1234")

            self.assertFalse(check["ok"])
            self.assertEqual(check["message_key"], "auth_password_reset_unavailable")
            self.assertFalse(reset["ok"])
            self.assertEqual(reset["message_key"], "auth_password_reset_unavailable")

    def test_generate_password_recovery_code_for_legacy_user_requires_current_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            salt = auth.secrets.token_bytes(16)
            legacy_users = {
                "legacy-user": {
                    "user_id": "legacy-user",
                    "display_name": "Legacy",
                    "username": "LegacyUser",
                    "email": "legacy@example.com",
                    "password_salt": auth.base64.b64encode(salt).decode("ascii"),
                    "password_hash": auth._hash_password("Password1234", salt),
                    "created_at": "2026-01-01 00:00:00",
                    "last_login_at": None,
                    "profile_state": "new",
                    "onboarding_pending": False,
                    "onboarding_completed_at": None,
                    "onboarding_do_not_show_again": False,
                    "onboarding_skipped_at": None,
                    "onboarding_version": auth.NEW_USER_ONBOARDING_VERSION,
                }
            }
            with open(users_path, "w", encoding="utf-8") as handle:
                json.dump(legacy_users, handle, ensure_ascii=False, indent=2)

            generated = auth.generate_password_recovery_code("legacy-user", "Password1234")

            self.assertTrue(generated["ok"])
            self.assertTrue(generated["user"]["password_recovery_ready"])
            verified = auth.verify_password_reset_recovery("legacy-user", generated["recovery_code"])
            self.assertTrue(verified["ok"])

    def test_tampered_users_envelope_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth, users_path, _, _ = self._reload_auth(tmpdir)
            auth.CREATE_USER_COOLDOWN_SECONDS = 0
            auth.CREATE_USER_MAX_IN_WINDOW = 99
            created = auth.create_user("alice", "Password1234", "Alice", "alice@example.com", require_email=True)
            self.assertTrue(created["ok"])
            envelope = self._assert_users_file_is_envelope_v2(users_path)
            envelope["hmac"] = "0" * 64
            with open(users_path, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, ensure_ascii=False, indent=2, sort_keys=True)

            self.assertEqual(auth._load_users(), {})
            self.assertEqual(auth.get_last_users_storage_state(), "integrity_error")
            blocked = auth.verify_user("alice", "Password1234")
            self.assertFalse(blocked["ok"])




if __name__ == "__main__":
    unittest.main()
