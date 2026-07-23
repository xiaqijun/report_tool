import asyncio
from unittest import TestCase
from unittest.mock import patch

from app.routers import api as api_router


class LlmSettingsApiTests(TestCase):
    class _JsonRequest:
        def __init__(self, payload=None):
            self._payload = payload or {}

        async def json(self):
            return self._payload

    def _run(self, coro):
        return asyncio.run(coro)

    def test_get_settings_reports_saved_key_without_exposing_it(self):
        settings = {
            "enabled": True,
            "api_base_url": "https://example.com/v1",
            "api_key": "stored-secret",
            "model": "grok-4.5",
            "timeout_seconds": 300,
            "source": "db",
        }

        with (
            patch("app.routers.api.require_login", return_value={"display_name": "Tester"}),
            patch("app.services.llm_settings.get_effective_llm_settings", return_value=settings),
        ):
            response = self._run(api_router.api_llm_settings(self._JsonRequest()))

        self.assertTrue(response["api_key_configured"])
        self.assertEqual(response["settings"]["api_key"], "")
        self.assertEqual(response["settings"]["model"], "grok-4.5")

    def test_save_settings_preserves_database_key_when_input_is_blank(self):
        current_settings = {
            "enabled": True,
            "api_base_url": "https://example.com/v1",
            "api_key": "stored-secret",
            "model": "grok-4.5",
            "timeout_seconds": 300,
            "source": "db",
        }
        submitted = {
            "enabled": True,
            "api_base_url": "https://example.com/v1/",
            "api_key": "",
            "model": "grok-4.5",
            "timeout_seconds": 120,
        }

        with (
            patch("app.routers.api.require_login", return_value={"display_name": "Tester"}),
            patch("app.services.llm_settings.get_effective_llm_settings", return_value=current_settings),
            patch("app.routers.api.db.save_llm_settings") as save_settings,
        ):
            response = self._run(api_router.api_save_llm_settings(self._JsonRequest(submitted)))

        self.assertEqual(response, {"success": True})
        save_settings.assert_called_once_with(
            {
                "enabled": True,
                "api_base_url": "https://example.com/v1",
                "api_key": "stored-secret",
                "model": "grok-4.5",
                "timeout_seconds": 120,
            }
        )
