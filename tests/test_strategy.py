import unittest
from types import SimpleNamespace

from app.strategy import analizar, rsi, rsi_serie, sma_serie, volatilidad_pct


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SimpleNamespace(
            sma_rapida=3, sma_lenta=5, rsi_periodo=3,
            rsi_sobrecompra=70, rsi_sobreventa=30,
        )

    def test_sma_is_aligned(self):
        self.assertEqual(sma_serie([1, 2, 3, 4], 3), [None, None, 2.0, 3.0])

    def test_rsi_for_only_gains_is_100(self):
        self.assertEqual(rsi([1, 2, 3, 4, 5], 3), 100.0)
        self.assertEqual(rsi_serie([1, 2, 3, 4, 5], 3)[-1], 100.0)

    def test_empty_market_is_safe(self):
        result = analizar([], self.cfg)
        self.assertEqual(result.señal, "MANTENER")
        self.assertEqual(result.confianza, 0)

    def test_analysis_exposes_professional_metrics(self):
        result = analizar([10, 10, 9, 8, 7, 8, 9, 10, 11], self.cfg)
        self.assertGreaterEqual(result.confianza, 0)
        self.assertLessEqual(result.confianza, 100)
        self.assertIsNotNone(result.volatilidad_pct)

    def test_probability_model_is_bounded_and_transparent(self):
        prices = [100.0]
        for index in range(60):
            prices.append(prices[-1] * (1.002 if index % 3 else 0.999))
        result = analizar(prices, self.cfg)
        self.assertIsNotNone(result.probabilidad_alcista_pct)
        self.assertAlmostEqual(
            result.probabilidad_alcista_pct + result.probabilidad_bajista_pct, 100.0, places=1
        )
        self.assertGreaterEqual(result.incertidumbre_pct, 0)
        self.assertLessEqual(result.incertidumbre_pct, 100)
        self.assertEqual(result.muestra_retornos, 50)
        self.assertIn("no-calibrado", result.modelo_probabilidad)

    def test_volatility_is_zero_for_flat_market(self):
        self.assertEqual(volatilidad_pct([10] * 22), 0.0)


if __name__ == "__main__":
    unittest.main()
