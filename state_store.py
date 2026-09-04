import json
import os
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent / "poller_state.json"


def carregar() -> dict:
    """Snapshot da última checagem: {"faturas": {invoice_pk: invoice_date_credit}}.
    Sem isso, todo ciclo do poller reenviaria notificação de tudo de novo.
    """
    if not STATE_PATH.exists():
        return {"faturas": {}}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar(estado: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass
