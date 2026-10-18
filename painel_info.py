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
    "ips_alterados": ("IPs permitidos alterados", {"acessos"}, "a"),
    "usuario_grupo_alterado": ("Grupo do usuário alterado", {"acessos"}, "a"),
    "usuario_bloqueado": ("Usuário bloqueado", {"acessos"}, "a"),
    "usuario_desbloqueado": ("Usuário desbloqueado", {"acessos"}, "a"),
    "grupo_criado": ("Grupo criado", {"acessos"}, "a"),
    "grupo_excluido": ("Grupo excluído", {"acessos"}, "a"),
    "permissoes_alteradas": ("Permissões alteradas", {"acessos"}, "a"),
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


def _intervalo_tipico(ciclos: list[dict]) -> timedelta:
    """Mediana dos intervalos entre os últimos ciclos, ignorando os menores que 5 min
    (ciclo rodado à mão logo depois de outro). Antes valia só o intervalo entre os
    dois últimos: um `systemctl start` manual reduzia a 1 min e o painel acusava
    "parado" em seguida."""
    horas = [q for q in (_quando(c) for c in ciclos[:12]) if q]
    intervalos = sorted(
        d for d in (a - b for a, b in zip(horas, horas[1:])) if d >= timedelta(minutes=5)
    )
    return intervalos[len(intervalos) // 2] if intervalos else timedelta(hours=1)


def status_poller(eventos: list[dict]) -> dict | None:
    """Último ciclo, próximo (pelo intervalo entre os dois últimos), falhas em 24h.
    None se o poller nunca registrou nada (instalação sem poller)."""
    ciclos = [e for e in eventos if e.get("evento") == "poller_ciclo"]
    falhas = [e for e in eventos if e.get("evento") == "poller_falha"]
    if not ciclos and not falhas:
        return None
    agora = datetime.now()
    ultimo = _quando(ciclos[0]) if ciclos else None
    intervalo = _intervalo_tipico(ciclos)
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


# ---- Notificações por cliente (envios.log, gravado pelo poller) ----

_TIPOS_ENVIO = {
    "pag": "Pagamento confirmado",
    "atr": "Cobrança de atraso",
    "ant": "Lembrete antecipado",
    "cha": "Chamado respondido",
}
# Bloqueio do fornecimento = vencimento + 7 dias corridos (regra do provedor, a mesma do app).
_DIAS_ATE_BLOQUEIO = 7


def formatar_documento(doc: str) -> str:
    """CPF 000.000.000-00, CNPJ 00.000.000/0000-00; outro formato fica como veio."""
    d = re.sub(r"\D", "", doc or "")
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return doc or ""


def _moeda(valor: str | None) -> str:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return ""
    return "R$ " + f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dia_mes(iso: str | None) -> str:
    try:
        return datetime.strptime((iso or "")[:10], "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return ""


def _partes_envio(e: dict) -> list[tuple[str, bool]]:
    """Trechos de "O que foi avisado" como (texto, destaque); o template escapa cada um."""
    tipo = e.get("tipo")
    contrato = e.get("contrato")
    partes: list[tuple[str, bool]] = []
    if tipo == "pag":
        partes += [(_moeda(e.get("valor")), True), (f"pago em {_dia_mes(e.get('pago_em'))}", False),
                   (f"venc. {_dia_mes(e.get('vencimento'))}", False)]
    elif tipo == "atr":
        bloqueio = ""
        try:
            bloqueio = (datetime.strptime(e.get("vencimento", "")[:10], "%Y-%m-%d")
                        + timedelta(days=_DIAS_ATE_BLOQUEIO)).strftime("%d/%m")
        except ValueError:
            pass
        partes += [(f"venceu {_dia_mes(e.get('vencimento'))}", False), (_moeda(e.get("valor")), True),
                   (f"bloqueio em {bloqueio}" if bloqueio else "", False)]
    elif tipo == "ant":
        dias = e.get("dias", "")
        quando = "amanhã" if dias == "1" else f"em {dias} dias"
        partes += [(f"vence {quando}", True), (f"({_dia_mes(e.get('vencimento'))})", False),
                   (_moeda(e.get("valor")), False)]
    elif tipo == "cha":
        partes += [(f"chamado nº {e.get('protocolo', '')}", True), (e.get("assunto", ""), False)]
    if contrato and tipo != "cha":
        partes.append((f"contrato {contrato}", False))
    if not e.get("ok", True):
        partes.append((f"não enviado: {e.get('erro', 'erro desconhecido')}", False))
    return [(texto, forte) for texto, forte in partes if texto and texto != "()"]


def _dia_e_hora(momento: datetime | None, agora: datetime) -> str:
    """Separador de ciclo sempre com a hora: 'hoje 18:00', 'ontem 23:00', '12/10 09:00'."""
    if momento is None:
        return ""
    if momento.date() == agora.date():
        return "hoje " + momento.strftime("%H:%M")
    if momento.date() == (agora - timedelta(days=1)).date():
        return "ontem " + momento.strftime("%H:%M")
    return momento.strftime("%d/%m %H:%M")


def envios_para_tabela(envios: list[dict]) -> list[dict]:
    agora = datetime.now()
    saida = []
    for e in envios:
        tipo = e.get("tipo", "")
        if tipo not in _TIPOS_ENVIO:
            continue
        momento = _quando(e)
        ok = e.get("ok", True)
        doc = formatar_documento(e.get("doc", ""))
        saida.append({
            "quando": e.get("quando", ""),
            "data": momento.strftime("%Y-%m-%d") if momento else "",
            "relativo": hora_relativa(momento, agora) or e.get("quando", ""),
            "ciclo": _dia_e_hora(momento, agora),
            "tipo": tipo,
            "classe": tipo if ok else "fal",
            "rotulo": _TIPOS_ENVIO[tipo] if ok else "Falha: " + _TIPOS_ENVIO[tipo].lower(),
            "ok": ok,
            "cliente": e.get("cliente") or "Cliente sem nome no cadastro",
            "doc": doc,
            "doc_digitos": re.sub(r"\D", "", doc),
            "partes": _partes_envio(e),
        })
    return saida
