import json
import threading
import time
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "acessos.log"

# Evita que o arquivo cresça pra sempre — mantém só os eventos mais
# recentes.
MAX_LINHAS = 1000

# O painel roda com threads (gunicorn gthread): sem trava, duas gravações ao
# mesmo tempo leriam o arquivo antigo e uma das linhas se perderia.
_trava = threading.Lock()


def registrar(evento: str, usuario: str = "", ip: str = "", detalhes: str = "", mensagem: str = "") -> None:
    entrada = {
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
        "evento": evento,
        "usuario": usuario,
        "ip": ip,
        "detalhes": detalhes,
    }
    # Texto do aviso enviado: "Últimos avisos" do painel oferece "Usar de novo".
    if mensagem:
        entrada["mensagem"] = mensagem
    with _trava:
        linhas = []
        if LOG_PATH.exists():
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                linhas = f.readlines()
        linhas.append(json.dumps(entrada, ensure_ascii=False) + "\n")
        linhas = linhas[-MAX_LINHAS:]
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(linhas)


def listar(limite: int = 200) -> list[dict]:
    """Devolve os eventos mais recentes primeiro."""
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        linhas = f.readlines()
    entradas = []
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
        try:
            entradas.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    return list(reversed(entradas))[:limite]
