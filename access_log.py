import json
import threading
import time
from contextlib import contextmanager

try:
    import fcntl  # Linux (servidor); no Windows de desenvolvimento só vale a trava de thread
except ImportError:
    fcntl = None
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "acessos.log"

# Evita que o arquivo cresça pra sempre — mantém só os eventos mais
# recentes.
MAX_LINHAS = 1000

# Sem trava, duas gravações ao mesmo tempo leriam o arquivo antigo e uma linha se
# perderia: entre threads do painel (gunicorn gthread) e entre o painel e o poller,
# que são processos diferentes (flock num arquivo de trava ao lado).
_trava = threading.Lock()
_ARQUIVO_TRAVA = LOG_PATH.with_name(".acessos.lock")


@contextmanager
def _travado():
    with _trava:
        if fcntl is None:
            yield
            return
        with open(_ARQUIVO_TRAVA, "a") as trava:
            fcntl.flock(trava, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(trava, fcntl.LOCK_UN)


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
    with _travado():
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
