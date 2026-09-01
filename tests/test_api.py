import unittest

from fastapi.testclient import TestClient

from app.config import config
from app.main import app


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


if __name__ == "__main__":
    unittest.main()
