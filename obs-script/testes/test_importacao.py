"""Todo arquivo do painel precisa abrir sem o OBS (o obspython só existe
dentro do OBS - ver testar_localmente.py). Pega erro de digitação, import
quebrado ou dependência faltando antes de chegar na live."""

import importlib
import pkgutil
import unittest

from testes import base  # noqa: F401

import kakazim_panel


class TesteImportacao(unittest.TestCase):
    def test_todos_os_modulos_abrem(self):
        nomes = [m.name for m in pkgutil.walk_packages(kakazim_panel.__path__, "kakazim_panel.")]
        self.assertGreater(len(nomes), 10)
        for nome in nomes:
            with self.subTest(modulo=nome):
                importlib.import_module(nome)


if __name__ == "__main__":
    unittest.main()
