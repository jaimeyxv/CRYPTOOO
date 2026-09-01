import unittest
from dataclasses import replace

from app.config import ConfigError, config


class ConfigTests(unittest.TestCase):
    def test_production_rejects_insecure_session(self):
        candidate = replace(
            config, environment="production", api_key="key", api_secret="secret",
            panel_password="a-strong-password", session_secret="x" * 48,
            cookie_secure=False, allowed_hosts=("example.com",),
        )
        with self.assertRaises(ConfigError):
            candidate.validar()

    def test_safe_mainnet_lock_is_reported_without_invalidating_development(self):
        candidate = replace(config, environment="development", use_testnet=False, enable_live_trading=False)
        warnings = candidate.validar()
        self.assertTrue(any("ENABLE_LIVE_TRADING" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
