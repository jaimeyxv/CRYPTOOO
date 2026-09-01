import unittest

from app import auth


class AuthTests(unittest.TestCase):
    def test_generated_token_is_valid(self):
        self.assertTrue(auth.token_valido(auth.crear_token()))

    def test_malformed_tokens_are_rejected(self):
        for token in (None, "", "x", "1.a.not-base64!", "0.a.YQ"):
            self.assertFalse(auth.token_valido(token))

    def test_login_limiter_blocks_repeated_failures(self):
        ip = "unit-test-ip"
        for _ in range(auth.MAX_INTENTOS):
            auth.registrar_login(ip, False)
        self.assertFalse(auth.login_permitido(ip))
        auth.registrar_login(ip, True)
        self.assertTrue(auth.login_permitido(ip))


if __name__ == "__main__":
    unittest.main()
