import json
import os
import shutil
import tempfile
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent / "poller_state.json"

# Folga mínima no disco para o ciclo começar: o estado, o envios.log e o
# acessos.log são regravados inteiros a cada ciclo.
MIN_LIVRE = 50 * 1024 * 1024


def carregar() -> dict:
    """O que o poller já viu, por categoria ("faturas", "faturas_atrasadas",
    "faturas_vence_amanha", "faturas_vence_em", "chamados"). Sem isso, todo ciclo
    reenviaria tudo de novo.

    Sem arquivo (instalação nova, arquivo apagado) devolve {}: nenhuma categoria
    presente, então o poller trata cada uma como primeira execução e só grava a
    baseline. Antes devolvia {"faturas": {}}, e a primeira execução notificava
    todo pagamento da janela de 90 dias.
    """
    if not STATE_PATH.exists():
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar(estado: dict) -> None:
    """Grava num temporário e troca de uma vez: se o processo cair no meio, o
    arquivo antigo continua inteiro (antes ficava corrompido e o poller parava)."""
    fd, temporario = tempfile.mkstemp(prefix=".poller_state-", dir=STATE_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
        try:
            os.chmod(temporario, 0o600)
        except OSError:
            pass
        os.replace(temporario, STATE_PATH)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise


def conferir_gravacao(estado: dict) -> None:
    """Antes de enviar qualquer aviso: confere a folga no disco e regrava o estado
    atual. Com o disco cheio (19/10/2026) os avisos saíam, o estado não gravava e o
    ciclo seguinte reenviava os mesmos pagamentos. Levanta OSError se não der."""
    livre = shutil.disk_usage(STATE_PATH.parent).free
    if livre < MIN_LIVRE:
        raise OSError(f"pouco espaço em disco ({livre // (1024 * 1024)} MB livres)")
    salvar(estado)
