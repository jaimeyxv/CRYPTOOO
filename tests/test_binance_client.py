import unittest
from unittest.mock import patch

from app.binance_client import BinanceClient, BinanceError


class BinanceClientTests(unittest.TestCase):
    def setUp(self):
        self.client = BinanceClient()

    def tearDown(self):
        self.client.cerrar()

    def test_quantity_is_rounded_down_to_step(self):
        self.assertEqual(self.client._ajustar_cantidad(1.239, "0.01"), "1.23")

    def test_invalid_interval_is_rejected_before_network(self):
        with self.assertRaises(BinanceError):
            self.client.klines(interval="13m")

    def test_symbol_filters_are_normalized(self):
        exchange = {"symbols": [{
            "baseAsset": "BTC", "quoteAsset": "USDT",
            "filters": [
                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.00001", "minQty": "0.0001", "maxQty": "10"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ],
        }]}
        with patch.object(self.client, "_request", return_value=exchange):
            info = self.client.info_simbolo("BTCUSDT")
        self.assertEqual(info["base"], "BTC")
        self.assertEqual(info["step"], "0.00001")
        self.assertEqual(info["min_notional"], 5.0)


if __name__ == "__main__":
    unittest.main()
