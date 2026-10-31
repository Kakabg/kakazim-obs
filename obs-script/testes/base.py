"""Base comum dos testes: coloca obs-script/ no caminho de importação e aponta
o painel pra uma pasta temporária, pra nunca tocar no data/ de verdade."""

import os
import sys
import tempfile

PASTA_OBS_SCRIPT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PASTA_OBS_SCRIPT not in sys.path:
    sys.path.insert(0, PASTA_OBS_SCRIPT)

from kakazim_panel import config  # noqa: E402

PASTA_TEMP = tempfile.mkdtemp(prefix="kakazim-obs-teste-")


def preparar_pasta_temporaria():
    """data/ vai pra pasta temporária; public/ continua sendo o de verdade
    (link simbólico ou cópia), pra o servidor conseguir servir a página."""
    publico_temp = os.path.join(PASTA_TEMP, "public")
    if not os.path.exists(publico_temp):
        try:
            os.symlink(os.path.join(PASTA_OBS_SCRIPT, "public"), publico_temp)
        except OSError:
            import shutil

            shutil.copytree(os.path.join(PASTA_OBS_SCRIPT, "public"), publico_temp)
    config.definir_diretorio_base(PASTA_TEMP)
    return PASTA_TEMP


preparar_pasta_temporaria()
