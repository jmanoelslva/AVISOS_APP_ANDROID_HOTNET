import json
import os
import stat
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "controllr_config.json"

_TEMPLATE = {
    "base_url": "https://AJUSTE_AQUI:0000/",
    "usuario": "AJUSTE_AQUI",
    "senha": "AJUSTE_AQUI",
}
# O intervalo de checagem não mora aqui — é controlado pelo systemd timer
# (controllr-poller.timer, OnUnitActiveSec), porque o poller roda uma vez
# e sai a cada chamada, sem loop/scheduler próprio.


def carregar() -> dict:
    """Config do usuário admin dedicado do Controllr, usado só pelo poller
    (não pelo painel web). Fica fora do git, igual a config.json e
    service-account.json — se não existir, cria um template e avisa.
    """
    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(_TEMPLATE, f, indent=2, ensure_ascii=False)
        try:
            os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        raise RuntimeError(
            f"controllr_config.json criado em {CONFIG_PATH} com valores de "
            "exemplo — preencha base_url, usuario e senha do usuário admin "
            "dedicado (só leitura) antes de rodar o poller."
        )

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    faltando = [
        chave for chave in ("base_url", "usuario", "senha")
        if not cfg.get(chave) or cfg[chave] == _TEMPLATE.get(chave)
    ]
    if faltando:
        raise RuntimeError(
            f"controllr_config.json incompleto — preencha: {', '.join(faltando)}"
        )
    return cfg
