import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.bot import Modo, estado
from app import bot
from app.storage import Storage
from app import trader


class FakeClient:
    def info_simbolo(self):
        return {"base": "BTC", "quote": "USDT"}

    def saldo_libre(self, asset):
        return 1000 if asset == "USDT" else 0.01

    def comprar_mercado(self, _):
        return {"orderId": 1, "executedQty": "0.01", "cummulativeQuoteQty": "100"}

    def vender_mercado(self, _):
        return {"orderId": 2, "executedQty": "0.01", "cummulativeQuoteQty": "110"}


class TraderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Storage(Path(self.tmp.name) / "test.db")
        self.store.initialize()
        self.patches = [
            patch.object(trader, "storage", self.store),
            patch.object(trader, "cliente", FakeClient()),
            patch.object(bot, "storage", self.store),
        ]
        for item in self.patches:
            item.start()
        estado.cambiar_modo(Modo.SENALES)

    def tearDown(self):
        estado.cambiar_modo(Modo.OFF)
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_complete_trade_updates_position_and_performance(self):
        buy = trader.comprar("unit test")
        self.assertTrue(buy["ok"])
        self.assertTrue(self.store.position()["en_posicion"])
        sell = trader.vender("unit test")
        self.assertTrue(sell["ok"])
        self.assertFalse(self.store.position()["en_posicion"])
        self.assertAlmostEqual(self.store.performance()["pnl_realizado"], 10)

    def test_second_buy_accumulates_position_at_weighted_average(self):
        with patch.object(trader, "config", replace(trader.config, cooldown_seg=0)):
            self.assertTrue(trader.comprar("first")["ok"])
            second = trader.comprar("second")
        self.assertTrue(second["ok"])
        position = self.store.position()
        self.assertAlmostEqual(position["cantidad"], 0.02)
        self.assertAlmostEqual(position["quote_spent"], 200)
        self.assertAlmostEqual(position["precio_entrada"], 10000)
        self.assertEqual(len(self.store.trades()), 2)


if __name__ == "__main__":
    unittest.main()
