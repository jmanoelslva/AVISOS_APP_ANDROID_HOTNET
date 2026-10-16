"""Dados de leitura do painel (sem chamar o Controllr nem o FCM): histórico de avisos,
saúde do poller e rótulos dos eventos de log. Tudo vem do próprio acessos.log."""
import re
import time
from datetime import datetime, timedelta

# Emojis prontos pro formulário de envio/modelos (P8). Pra mudar a lista, edite aqui.
EMOJIS = [
    ("Rede", ["📶", "🌐", "🔧", "🛠️", "🚧", "⚡", "🌧️", "📡", "📍", "🔌"]),
    ("Horário", ["🕐", "⏰", "⏳", "📅", "🗓️", "🌙"]),
    ("Status", ["⚠️", "❗", "ℹ️", "✅", "🟢", "🔴", "🟡", "🔄"]),
    ("Atendimento", ["📢", "📞", "💬", "🙏", "👍", "💳", "🧾", "🎉"]),
]

# evento -> (rótulo, categorias pro filtro, classe da etiqueta)
_EVENTOS = {
    "login_sucesso": ("Login", {"acessos"}, "s"),
    "login_falha": ("Login recusado", {"acessos", "falhas"}, "f"),
    "aviso_enviado": ("Aviso enviado", {"avisos"}, "v"),
    "aviso_falha": ("Falha ao enviar aviso", {"avisos", "falhas"}, "f"),
    "usuario_criado": ("Usuário criado", {"acessos"}, "a"),
    "usuario_removido": ("Usuário removido", {"acessos"}, "a"),
    "senha_alterada": ("Senha alterada", {"acessos"}, "a"),
    "lembretes_alterados": ("Lembretes alterados", {"acessos"}, "a"),
    "porta_alterada": ("Porta alterada", {"acessos"}, "a"),
    "poller_ciclo": ("Ciclo automático", {"poller"}, "p"),
    "poller_falha": ("Falha automática", {"poller", "falhas"}, "f"),
}

_FORMATO = "%Y-%m-%d %H:%M:%S"
_NOTIFICADOS = re.compile(r"(\d+) [^\d,()]*notificad")


def _quando(evento: dict) -> datetime | None:
    try:
        return datetime.strptime(evento.get("quando", ""), _FORMATO)
    except ValueError:
        return None


def hora_relativa(momento: datetime | None, agora: datetime | None = None) -> str:
    """'há 5 min', 'hoje 10:12', 'ontem 23:01', '12/10 18:40'."""
    if momento is None:
        return ""
    agora = agora or datetime.now()
    segundos = (agora - momento).total_seconds()
    if 0 <= segundos < 60:
        return "agora"
    if 0 <= segundos < 3600:
        return f"há {int(segundos // 60)} min"
    if momento.date() == agora.date():
        return "hoje " + momento.strftime("%H:%M")
    if momento.date() == (agora - timedelta(days=1)).date():
        return "ontem " + momento.strftime("%H:%M")
    return momento.strftime("%d/%m %H:%M")


def ciclo_notificou(detalhes: str) -> bool:
    """Ciclo do poller que mandou alguma notificação (ou gravou baseline)."""
    numeros = [int(n) for n in _NOTIFICADOS.findall(detalhes or "")]
    return not numeros or any(numeros)


def eventos_para_tabela(eventos: list[dict]) -> list[dict]:
    agora = datetime.now()
    saida = []
    for e in eventos:
        rotulo, categorias, classe = _EVENTOS.get(e.get("evento", ""), (e.get("evento", ""), set(), "a"))
        momento = _quando(e)
        vazio = e.get("evento") == "poller_ciclo" and not ciclo_notificou(e.get("detalhes", ""))
        saida.append({
            **e,
            "rotulo": rotulo,
            "categorias": " ".join(sorted(categorias)),
            "classe": classe,
            "relativo": hora_relativa(momento, agora) or e.get("quando", ""),
            "ciclo_vazio": vazio,
            "quem": e.get("usuario") or ("sistema" if e.get("evento", "").startswith("poller") else ""),
        })
    return saida


def ultimos_avisos(eventos: list[dict], limite: int = 5) -> list[dict]:
    agora = datetime.now()
    avisos = [e for e in eventos if e.get("evento") == "aviso_enviado"][:limite]
    return [{**e, "relativo": hora_relativa(_quando(e), agora)} for e in avisos]


def status_poller(eventos: list[dict]) -> dict | None:
    """Último ciclo, próximo (pelo intervalo entre os dois últimos), falhas em 24h.
    None se o poller nunca registrou nada (instalação sem poller)."""
    ciclos = [e for e in eventos if e.get("evento") == "poller_ciclo"]
    falhas = [e for e in eventos if e.get("evento") == "poller_falha"]
    if not ciclos and not falhas:
        return None
    agora = datetime.now()
    ultimo = _quando(ciclos[0]) if ciclos else None
    anterior = _quando(ciclos[1]) if len(ciclos) > 1 else None
    intervalo = (ultimo - anterior) if ultimo and anterior else timedelta(hours=1)
    if intervalo <= timedelta(0):
        intervalo = timedelta(hours=1)
    proximo = ultimo + intervalo if ultimo else None
    falhas_24h = sum(1 for e in falhas if (q := _quando(e)) and agora - q <= timedelta(hours=24))
    parado = ultimo is None or agora - ultimo > 2 * intervalo
    minutos = int(intervalo.total_seconds() // 60)
    return {
        "ultimo_hora": ultimo.strftime("%H:%M") if ultimo else "—",
        "ultimo_relativo": hora_relativa(ultimo, agora) if ultimo else "nenhum ciclo ainda",
        "proximo_hora": proximo.strftime("%H:%M") if proximo else "—",
        "intervalo": "de hora em hora" if minutos == 60 else f"a cada {minutos} min",
        "falhas_24h": falhas_24h,
        "parado": parado,
        "resumo": ciclos[0].get("detalhes", "") if ciclos else "",
    }


# Contagem do dia por tipo, somando os ciclos de hoje (texto gravado pelo poller.py).
_CONTAGENS = {
    "pagamentos": re.compile(r"\((\d+) pagamentos notificados\)"),
    "chamados": re.compile(r"chamados \((\d+) notificados\)"),
    "atrasos": re.compile(r"(\d+) atrasos notificados"),
    "lembretes": re.compile(r"(\d+) (?:lembretes de vencimento|vence-amanhã) notificados"),
}


def contagens_hoje(eventos: list[dict]) -> dict:
    hoje = datetime.now().date()
    total = {chave: 0 for chave in _CONTAGENS}
    for e in eventos:
        if e.get("evento") != "poller_ciclo" or not (q := _quando(e)) or q.date() != hoje:
            continue
        for chave, regex in _CONTAGENS.items():
            total[chave] += sum(int(n) for n in regex.findall(e.get("detalhes", "")))
    return total


def status_topo(eventos: list[dict]) -> dict | None:
    """Selo do topo: ok / alerta (falhas em 24h) / parado. None sem poller."""
    st = status_poller(eventos)
    if st is None:
        return None
    if st["parado"]:
        return {"nivel": "parado", "texto": "Automáticos parados"}
    if st["falhas_24h"]:
        n = st["falhas_24h"]
        return {"nivel": "alerta", "texto": f"{n} falha{'s' if n > 1 else ''} · {st['ultimo_hora']}"}
    return {"nivel": "ok", "texto": f"Automáticos ok · {st['ultimo_hora']}"}


def agora_hhmm() -> str:
    return time.strftime("%H:%M")
