import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import config
from app.main import app
from app.bot import Modo, estado


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def setUp(self):
        self.client.cookies.clear()

    def test_liveness_and_readiness(self):
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])
        self.assertEqual(health.headers["x-frame-options"], "DENY")
        self.assertEqual(self.client.get("/readyz").status_code, 200)

    def test_private_endpoint_requires_session(self):
        response = self.client.get("/api/configuracion")
        self.assertEqual(response.status_code, 401)

    def test_login_creates_httponly_cookie(self):
        response = self.client.post("/api/login", data={"pin": config.panel_password})
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        private = self.client.get("/api/configuracion")
        self.assertEqual(private.status_code, 200)
        self.assertNotIn("api_secret", private.json())
        export = self.client.get("/api/historial.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.headers["content-type"])

    def test_unexpected_order_error_is_returned_as_traceable_json(self):
        self.client.post("/api/login", data={"pin": config.panel_password})
        estado.cambiar_modo(Modo.SENALES)
        try:
            with patch("app.main.trader.vender", side_effect=RuntimeError("simulated")):
                response = self.client.post("/api/orden", data={"tipo": "VENDER"})
            self.assertEqual(response.status_code, 500)
            payload = response.json()
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["tipo_error"], "RuntimeError")
            self.assertTrue(payload["incidente"])
            self.assertEqual(payload["incidente"], response.headers["x-request-id"])
        finally:
            estado.cambiar_modo(Modo.OFF)


if __name__ == "__main__":
    unittest.main()
