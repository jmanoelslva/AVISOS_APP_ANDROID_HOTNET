import json
import os
import tempfile
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent / "poller_state.json"


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
