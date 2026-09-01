import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import bot
from app.bot import EstadoBot, Modo
from app.storage import Storage


class BotPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Storage(Path(self.tmp.name) / "state.db")
        self.store.initialize()
        self.storage_patch = patch.object(bot, "storage", self.store)
        self.storage_patch.start()

    def tearDown(self):
        self.storage_patch.stop()
        self.tmp.cleanup()

    def test_auto_mode_survives_restart_and_emergency_stop_does_too(self):
        first = EstadoBot()
        first.cambiar_modo(Modo.AUTO)

        restarted = EstadoBot()
        self.assertEqual(restarted.restaurar_modo(), Modo.AUTO)
        self.assertEqual(restarted.modo, Modo.AUTO)

        restarted.parada_emergencia()
        after_stop = EstadoBot()
        self.assertEqual(after_stop.restaurar_modo(), Modo.OFF)
        self.assertEqual(after_stop.modo, Modo.OFF)


if __name__ == "__main__":
    unittest.main()
