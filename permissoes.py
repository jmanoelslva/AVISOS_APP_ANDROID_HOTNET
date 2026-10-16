"""Grupos de usuários e permissões do painel.

Cada usuário pertence a um grupo (config.json: usuarios[].grupo); o grupo define o
que ele vê e altera. "Administrador" é fixo, sempre com todas as permissões, e não
fica gravado em config.json["grupos"]. As permissões são conferidas no servidor a
cada pedido (app.py); esconder botões e abas é só conforto.
"""
import re

GRUPO_ADMIN = "Administrador"
GRUPO_PADRAO = "Atendimento"

# (seção, [(id, nome, descrição, mostra dados de clientes)])
SECOES = [
    ("Avisos", [
        ("enviar", "Enviar aviso geral", "Aba Enviar; dispara para todos os clientes com o app", False),
        ("modelos", "Gerenciar modelos", "Criar, editar e excluir modelos (usar um modelo vem com Enviar)", False),
    ]),
    ("Automáticos", [
        ("ver_automaticos", "Ver automáticos", "Funcionamento do poller e avisos do dia", False),
        ("lembretes", "Alterar lembretes", "Antecedência, aviso de atraso e horário", False),
    ]),
    ("Histórico", [
        ("historico", "Ver histórico de eventos", "Logins, avisos enviados, alterações e ciclos", False),
        ("notificacoes", "Ver notificações de clientes", "Nome, CPF/CNPJ e valores de cada aviso automático", True),
    ]),
    ("Administração", [
        ("rede", "Alterar porta e IPs permitidos", "Ajustes → Acesso e rede", False),
        ("usuarios", "Gerenciar usuários e grupos", "Só no grupo Administrador", False),
    ]),
]
TODAS = [p[0] for _, itens in SECOES for p in itens]
# Quem gerencia usuários pode se dar qualquer permissão: na prática é administrador.
SO_ADMIN = {"usuarios"}
# Permissão que depende de outra (alterar lembretes exige ver a tela).
DEPENDE = {"lembretes": "ver_automaticos"}
# O que os usuários não administradores podiam fazer até a 1.4.x.
PERMISSOES_ATENDIMENTO = ["enviar", "modelos", "ver_automaticos", "historico", "notificacoes"]

_NOME_VALIDO = re.compile(r"^[\wÀ-ÿ][\wÀ-ÿ .-]{1,29}$")


def limpar(perms) -> list[str]:
    """Só permissões conhecidas, sem as exclusivas do admin, com as dependências."""
    escolhidas = {p for p in perms or [] if p in TODAS and p not in SO_ADMIN}
    for p, requisito in DEPENDE.items():
        if p in escolhidas:
            escolhidas.add(requisito)
    return [p for p in TODAS if p in escolhidas]


def validar_nome(nome: str, grupos: list[dict]) -> str | None:
    """Mensagem de erro, ou None se o nome serve para um grupo novo."""
    if not _NOME_VALIDO.match(nome or ""):
        return "use de 2 a 30 caracteres: letras, números, espaço, ponto ou hífen"
    existentes = {GRUPO_ADMIN.lower()} | {g["nome"].lower() for g in grupos}
    if nome.lower() in existentes:
        return "já existe um grupo com esse nome"
    return None


def migrar(cfg: dict) -> bool:
    """Coloca usuários e grupos no formato da 1.5.0. Devolve True se mudou algo.
    Admins vão para Administrador; os demais para Atendimento, com as mesmas
    permissões que tinham. Mantém is_admin em dia, para um retorno à 1.4.x."""
    alterou = False
    grupos = cfg.get("grupos")
    if not isinstance(grupos, list):
        grupos = [{"nome": GRUPO_PADRAO, "permissoes": list(PERMISSOES_ATENDIMENTO)}]
        cfg["grupos"] = grupos
        alterou = True
    nomes = {g.get("nome") for g in grupos}
    for g in grupos:
        limpas = limpar(g.get("permissoes"))
        if limpas != g.get("permissoes"):
            g["permissoes"] = limpas
            alterou = True
    for u in cfg.get("usuarios", []):
        grupo = u.get("grupo")
        if grupo != GRUPO_ADMIN and grupo not in nomes:
            if grupo is None and u.get("is_admin"):
                u["grupo"] = GRUPO_ADMIN
            else:
                if GRUPO_PADRAO not in nomes:
                    grupos.append({"nome": GRUPO_PADRAO, "permissoes": list(PERMISSOES_ATENDIMENTO)})
                    nomes.add(GRUPO_PADRAO)
                u["grupo"] = GRUPO_PADRAO
            alterou = True
        if "ativo" not in u:
            u["ativo"] = True
            alterou = True
        admin = u["grupo"] == GRUPO_ADMIN
        if u.get("is_admin") != admin:
            u["is_admin"] = admin
            alterou = True
    return alterou


def do_usuario(cfg: dict, entrada: dict | None) -> set[str]:
    """Permissões efetivas; vazio para usuário inexistente ou bloqueado."""
    if not entrada or not entrada.get("ativo", True):
        return set()
    # Sem grupo (gravado por fora antes da migração): segue o is_admin, como na 1.4.x.
    nome = entrada.get("grupo") or (GRUPO_ADMIN if entrada.get("is_admin") else GRUPO_PADRAO)
    if nome == GRUPO_ADMIN:
        return set(TODAS)
    grupo = next((g for g in cfg.get("grupos", []) if g.get("nome") == nome), None)
    if grupo is None and nome == GRUPO_PADRAO:
        return set(PERMISSOES_ATENDIMENTO)
    return set(limpar(grupo.get("permissoes") if grupo else []))


def admins_ativos(cfg: dict) -> list[str]:
    return [u["username"] for u in cfg.get("usuarios", [])
            if u.get("grupo") == GRUPO_ADMIN and u.get("ativo", True)]
