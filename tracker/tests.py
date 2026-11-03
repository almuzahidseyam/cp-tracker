import re
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch, MagicMock
from django.core import mail
from django.core.cache import cache
from django.db import connection, close_old_connections
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from .models import CustomUser, LoginChallenge, UserHandle, RecentSubmission, Friendship
from .authentication import issue_challenge, consume_challenge, reserve_cooldown
from .services import (
    update_user_handle_stats,
    fetch_atcoder_data,
    fetch_codechef_data,
    fetch_leetcode_data,
)

STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
TEST_SETTINGS = {
    "SECURE_SSL_REDIRECT": False,
    "STORAGES": STORAGE,
    "EMAIL_LOGIN_ENABLED": True,
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}


@override_settings(**TEST_SETTINGS)
class LoginTests(TestCase):
    def start(self, email="alice@example.com"):
        response = self.client.post("/login/", {"email": email})
        self.assertEqual(response.status_code, 302)
        code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
        identifier = self.client.session["login_challenge"]
        return identifier, code

    def test_code_is_hashed_single_use_and_session_is_rotated(self):
        identifier, code = self.start()
        row = LoginChallenge.objects.get(pk=identifier)
        self.assertNotEqual(row.code_hash, code)
        previous_session = self.client.session.session_key
        response = self.client.post("/verify/", {"otp": code})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertNotEqual(previous_session, self.client.session.session_key)
        self.assertNotIn("login_challenge", self.client.session)
        row.refresh_from_db()
        self.assertIsNotNone(row.consumed_at)
        self.assertEqual(row.code_hash, "")
        self.assertIsNone(consume_challenge(identifier, code))
        row.user.refresh_from_db()
        self.assertTrue(row.user.is_active)
        self.assertTrue(row.user.activation_locked)

    def test_five_wrong_attempts_block_even_correct_code(self):
        identifier, code = self.start()
        wrong = "999999" if code != "999999" else "000000"
        for _ in range(5):
            self.client.post("/verify/", {"otp": wrong})
        row = LoginChallenge.objects.get(pk=identifier)
        self.assertEqual(row.attempts, 5)
        self.assertIsNotNone(row.consumed_at)
        self.assertIsNone(consume_challenge(identifier, code))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_expiry_at_exact_boundary_and_cooldown(self):
        identifier, code = self.start()
        self.assertEqual(
            self.client.post("/login/", {"email": "ALICE@example.com"}).status_code, 429
        )
        row = LoginChallenge.objects.get(pk=identifier)
        with patch("tracker.authentication.timezone.now", return_value=row.expires_at):
            self.assertIsNone(consume_challenge(identifier, code))

    def test_resend_replaces_previous_code_and_old_login_form_remains_usable(self):
        identifier, old_code = self.start()
        user = CustomUser.objects.get(email="alice@example.com")
        CustomUser.objects.filter(pk=user.pk).update(
            otp_last_sent_at=timezone.now() - timedelta(seconds=61)
        )
        self.assertContains(self.client.get("/login/"), 'name="email"')
        new_id, new_code = self.start()
        self.assertNotEqual(new_id, identifier)
        self.assertIsNone(consume_challenge(identifier, old_code))
        self.assertIsNotNone(consume_challenge(new_id, new_code))

    def test_disabled_user_cannot_be_reactivated(self):
        CustomUser.objects.create_user(
            "disabled@example.com", is_active=False, activation_locked=True
        )
        self.assertEqual(
            self.client.post("/login/", {"email": "disabled@example.com"}).status_code,
            429,
        )
        self.assertFalse(CustomUser.objects.get(email="disabled@example.com").is_active)
        self.assertFalse(LoginChallenge.objects.exists())

    @patch("tracker.views.send_mail", side_effect=OSError("smtp-password-secret"))
    def test_mail_failure_invalidates_challenge_without_leaking_error(self, send):
        response = self.client.post("/login/", {"email": "alice@example.com"})
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "smtp-password-secret", status_code=503)
        self.assertIsNotNone(LoginChallenge.objects.get().consumed_at)

    def test_missing_mail_configuration_invalid_email_and_csrf(self):
        with override_settings(EMAIL_LOGIN_ENABLED=False):
            self.assertEqual(
                self.client.post("/login/", {"email": "alice@example.com"}).status_code,
                503,
            )
        self.assertEqual(
            self.client.post("/login/", {"email": "invalid"}).status_code, 400
        )
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post("/login/", {"email": "alice@example.com"}).status_code, 403
        )

    def test_email_rate_budget_shared_across_sessions_and_ip_limit(self):
        for index in range(5):
            self.assertIsNotNone(
                issue_challenge("rate@example.com", "ip-" + str(index))
            )
            CustomUser.objects.filter(email="rate@example.com").update(
                otp_last_sent_at=timezone.now() - timedelta(seconds=61)
            )
        self.assertIsNone(issue_challenge("rate@example.com", "different-ip"))
        for index in range(20):
            self.assertIsNotNone(issue_challenge(f"ip{index}@example.com", "same-ip"))
        self.assertIsNone(issue_challenge("last@example.com", "same-ip"))


@override_settings(**TEST_SETTINGS)
class HandleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = CustomUser.objects.create_user(
            "owner@example.com", is_active=True, activation_locked=True
        )
        self.client.force_login(self.user)
        self.handle = UserHandle.objects.create(
            user=self.user, platform="CF", handle="old-handle", total_solves=123
        )
        RecentSubmission.objects.create(
            handle=self.handle,
            problem_name="Old history",
            problem_url="https://example.com",
            timestamp=timezone.now(),
        )

    @patch("tracker.views.fetch_handle_stats", return_value=None)
    def test_failed_replacement_preserves_previous_handle_and_history(self, fetch):
        self.client.post("/settings/", {"platform": "CF", "handle": "missing-user"})
        self.handle.refresh_from_db()
        self.assertEqual(self.handle.handle, "old-handle")
        self.assertEqual(self.handle.total_solves, 123)
        self.assertEqual(self.handle.recent_submissions.count(), 1)

    @patch(
        "tracker.views.fetch_handle_stats",
        return_value={"total_solves": 0, "recent_submissions": []},
    )
    def test_valid_empty_account_replaces_and_clears_old_history(self, fetch):
        self.client.post("/settings/", {"platform": "CF", "handle": "new-user"})
        self.handle.refresh_from_db()
        self.assertEqual(self.handle.handle, "new-user")
        self.assertEqual(self.handle.total_solves, 0)
        self.assertEqual(self.handle.recent_submissions.count(), 0)

    @patch("tracker.views.fetch_handle_stats")
    def test_reject_invalid_platform_and_handle_before_fetch(self, fetch):
        for platform, handle in [
            ("OTHER", "abc"),
            ("CF", "x&count=1"),
            ("CC", "../x"),
            ("CF", ""),
        ]:
            self.client.post("/settings/", {"platform": platform, "handle": handle})
        fetch.assert_not_called()

    @patch(
        "tracker.services.fetch_handle_stats",
        return_value={"total_solves": 9, "recent_submissions": []},
    )
    def test_background_refresh_cannot_undo_a_concurrent_edit(self, fetch):
        UserHandle.objects.filter(pk=self.handle.pk).update(handle="concurrent-change")
        self.assertFalse(update_user_handle_stats(self.handle))
        self.handle.refresh_from_db()
        self.assertEqual(self.handle.handle, "concurrent-change")

    @patch("tracker.services.requests.get")
    @patch("tracker.services.requests.post")
    def test_dashboard_is_snapshot_only_and_leaderboard_has_no_duplicate_sum(
        self, post, get
    ):
        for index in range(3):
            follower = CustomUser.objects.create_user(
                f"friend{index}@example.com", is_active=True
            )
            Friendship.objects.create(follower=follower, followed=self.user)
        self.assertEqual(self.client.get("/").status_code, 200)
        post.assert_not_called()
        get.assert_not_called()
        rows = self.client.get("/leaderboard/").context["leaderboard_data"]
        self.assertEqual(rows[0]["total_solves"], 123)

    def test_owner_cannot_delete_another_users_handle(self):
        other = CustomUser.objects.create_user("other@example.com", is_active=True)
        handle = UserHandle.objects.create(user=other, platform="LC", handle="other")
        self.client.post(f"/handle/delete/{handle.pk}/")
        self.assertTrue(UserHandle.objects.filter(pk=handle.pk).exists())

    @patch("tracker.views.update_user_handle_stats", return_value=True)
    def test_cron_requires_configured_header_and_obeys_budget(self, refresh):
        with override_settings(CRON_SECRET=""):
            self.assertEqual(
                self.client.get(
                    "/api/cron/refresh/?token=my-super-secret-cron-token"
                ).status_code,
                503,
            )
        key = "fixture-cron-key-0123456789abcdef0123456789"
        with override_settings(CRON_SECRET=key):
            self.assertEqual(
                self.client.get("/api/cron/refresh/?token=" + key).status_code, 401
            )
            self.assertEqual(
                self.client.get(
                    "/api/cron/refresh/", HTTP_AUTHORIZATION="Bearer " + key
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.get(
                    "/api/cron/refresh/", HTTP_AUTHORIZATION="Bearer " + key
                ).status_code,
                429,
            )
        refresh.assert_called_once()


class ProviderEdgeTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("tracker.services.requests.post")
    def test_missing_leetcode_user_is_not_a_valid_zero_solve_profile(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "data": {
                "matchedUser": None,
                "userContestRanking": None,
                "recentAcSubmissionList": [],
            }
        }
        self.assertIsNone(fetch_leetcode_data("missing"))

    @patch("tracker.services.requests.get")
    def test_codechef_missing_counter_is_unavailable_not_zero(self, get):
        get.return_value.status_code = 200
        get.return_value.text = "Please complete CAPTCHA"
        self.assertIsNone(fetch_codechef_data("someone"))

    @patch("tracker.services.requests.get")
    def test_atcoder_uses_lifetime_aggregate_not_first_submission_page(self, get):
        profile = MagicMock(status_code=200)
        aggregate = MagicMock()
        aggregate.json.return_value = {"count": 2193, "rank": 1148}
        get.side_effect = [profile, aggregate]
        self.assertEqual(fetch_atcoder_data("kenkoooo")["total_solves"], 2193)
        self.assertIn("/user/ac_rank", get.call_args.args[0])

    def test_provider_cooldown_does_not_reset_at_window_boundary(self):
        now = timezone.now()
        with patch("tracker.authentication.timezone.now", return_value=now):
            self.assertTrue(reserve_cooldown("provider", 1.1))
        with patch(
            "tracker.authentication.timezone.now",
            return_value=now + timedelta(seconds=1),
        ):
            self.assertFalse(reserve_cooldown("provider", 1.1))
        with patch(
            "tracker.authentication.timezone.now",
            return_value=now + timedelta(seconds=1.2),
        ):
            self.assertTrue(reserve_cooldown("provider", 1.1))


class MigrationTests(TransactionTestCase):
    def test_migration_preserves_disabled_accounts_and_discards_legacy_otp(self):
        executor = MigrationExecutor(connection)
        old = [("tracker", "0005_recentsubmission")]
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            old_user = apps.get_model("tracker", "CustomUser").objects.create(
                email="legacy@example.com",
                is_active=False,
                otp_code="123456",
                otp_created_at=timezone.now(),
            )
            MigrationExecutor(connection).migrate(latest)
            user = CustomUser.objects.get(pk=old_user.pk)
            self.assertFalse(user.is_active)
            self.assertTrue(user.activation_locked)
            self.assertIsNone(issue_challenge(user.email, "fixture-ip"))
        finally:
            MigrationExecutor(connection).migrate(latest)


@skipUnless(
    connection.vendor == "postgresql",
    "Concurrent row-lock behavior is verified in the PostgreSQL CI job.",
)
class ConcurrentOtpTests(TransactionTestCase):
    def test_two_concurrent_valid_submissions_consume_code_once(self):
        challenge, code = issue_challenge("concurrent@example.com", "fixture-ip")

        def consume(_):
            close_old_connections()
            try:
                return consume_challenge(challenge.pk, code) is not None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, range(2)))
        self.assertEqual(sorted(results), [False, True])
