import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Storage(Path(self.tmp.name) / "aurum.db")
        self.store.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_buy_and_sell_are_persisted_transactionally(self):
        position = {
            "symbol": "BTCUSDT", "cantidad": 0.01, "precio_entrada": 100,
            "quote_spent": 1, "hora": "2026-01-01T00:00:00+00:00", "order_id": "buy-1",
        }
        buy = {
            "symbol": "BTCUSDT", "side": "BUY", "quantity": 0.01, "price": 100,
            "quote_quantity": 1, "reason": "test", "order_id": "buy-1", "mode": "SENALES",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        self.store.record_buy(position, buy)
        self.assertTrue(self.store.position()["en_posicion"])

        sell = {
            "symbol": "BTCUSDT", "side": "SELL", "quantity": 0.01, "price": 110,
            "quote_quantity": 1.1, "realized_pnl": 0.1, "realized_pnl_pct": 10,
            "reason": "take-profit", "order_id": "sell-1", "mode": "AUTO",
            "created_at": "2026-01-01T01:00:00+00:00",
        }
        self.store.record_sell(sell)
        self.assertFalse(self.store.position()["en_posicion"])
        performance = self.store.performance()
        self.assertEqual(performance["operaciones_cerradas"], 1)
        self.assertEqual(performance["win_rate"], 100.0)
        self.assertAlmostEqual(performance["pnl_realizado"], 0.1)

    def test_events_are_bounded_and_ordered(self):
        self.store.add_event("INFO", "test", "primero")
        self.store.add_event("ERROR", "test", "segundo")
        events = self.store.events(10)
        self.assertEqual(events[0]["message"], "segundo")
        self.assertTrue(self.store.healthy())


if __name__ == "__main__":
    unittest.main()
