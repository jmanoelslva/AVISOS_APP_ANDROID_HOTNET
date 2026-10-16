import ipaddress
import os
import signal
import socket
import threading
import time
import uuid
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from werkzeug.security import check_password_hash, generate_password_hash

import access_log
import envios_log
import config_store
import lembretes
import painel_info
import permissoes
from fcm_sender import enviar_aviso
from security import validar_forca_senha

app = Flask(__name__)
app.secret_key = config_store.carregar()["secret_key"]
csrf = CSRFProtect(app)

# O painel roda atrás de um Apache fazendo proxy reverso. Por padrão o
# cookie de sessão não exige HTTPS (senão logins quebrariam em instalações
# só-HTTP numa rede interna). Se o Apache na frente já terminar TLS,
# defina AVISO_BROADCASTER_HTTPS=1 no serviço systemd (ver README) pra
# marcar o cookie como Secure.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("AVISO_BROADCASTER_HTTPS") == "1"


@app.errorhandler(CSRFError)
def csrf_invalido(e):
    flash("Sessão expirada ou formulário inválido — tente de novo.", "erro")
    destino = request.referrer or url_for("login")
    return redirect(destino)

# Bloqueio simples por IP após tentativas de senha erradas seguidas —
# guardado em memória (reinicia se o serviço reiniciar, o que é aceitável
# pra um painel de baixo tráfego como esse).
_tentativas_login: dict[str, tuple[int, float]] = {}
_MAX_TENTATIVAS = 5
_BLOQUEIO_SEGUNDOS = 300


def _ip_do_cliente() -> str:
    # Se estiver atrás de um proxy reverso (Nginx), confia no
    # X-Forwarded-For; senão usa o IP direto da conexão.
    encaminhado = request.headers.get("X-Forwarded-For")
    bruto = encaminhado.split(",")[0].strip() if encaminhado else (request.remote_addr or "")

    # O servidor escuta em "[::]" (dual-stack IPv6+IPv4) — clientes IPv4
    # chegam como um endereço "IPv4-mapped" (ex: "::ffff:203.0.113.5").
    # Sem isso, uma ACL cadastrada em IPv4 puro (ex: "203.0.113.0/24")
    # pararia de bater com esses clientes silenciosamente.
    try:
        endereco = ipaddress.ip_address(bruto)
    except ValueError:
        return bruto
    if isinstance(endereco, ipaddress.IPv6Address) and endereco.ipv4_mapped:
        return str(endereco.ipv4_mapped)
    return str(endereco)


@app.before_request
def checar_acl():
    cfg = config_store.carregar()
    permitidos = cfg.get("allowed_ips") or []
    if not permitidos:
        return  # ACL vazia = sem restrição de IP (ver aviso na tela de configurações)
    ip_cliente = _ip_do_cliente()
    for faixa in permitidos:
        try:
            if ipaddress.ip_address(ip_cliente) in ipaddress.ip_network(faixa, strict=False):
                return
        except ValueError:
            continue
    abort(403)


def login_obrigatorio(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Exige também "usuario" na sessão, não só "autenticado" — sessões
        # antigas (de antes do suporte a múltiplos usuários) tinham
        # autenticado=True mas nunca guardaram o nome de usuário, o que
        # travava silenciosamente qualquer ação que precisasse saber quem
        # está logado (ex: trocar senha, criar novo usuário). Nesse caso,
        # força um login novo em vez de deixar a sessão incompleta.
        if not session.get("autenticado") or not session.get("usuario"):
            session.clear()
            return redirect(url_for("login"))
        # Usuário removido ou bloqueado perde a sessão já aberta no próximo clique.
        entrada = _entrada_usuario_logado(config_store.carregar())
        if not entrada or not entrada.get("ativo", True):
            session.clear()
            flash("Seu acesso ao painel foi encerrado. Fale com o administrador.", "erro")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def _entrada_usuario_logado(cfg: dict) -> dict | None:
    usuario_logado = session.get("usuario")
    return next(
        (u for u in cfg.get("usuarios", []) if u["username"] == usuario_logado), None
    )


def _permissoes_logado() -> set[str]:
    cfg = config_store.carregar()
    return permissoes.do_usuario(cfg, _entrada_usuario_logado(cfg))


# Primeira página que o grupo pode abrir (login e logotipo levam para ela).
_PAGINAS = [
    ("enviar", "dashboard"), ("ver_automaticos", "automaticos"), ("modelos", "modelos"),
    ("historico", "logs"), ("notificacoes", "logs"), ("usuarios", "configuracoes"), ("rede", "configuracoes"),
]


def _pagina_inicial(perms: set[str]) -> str:
    for perm, endpoint in _PAGINAS:
        if perm in perms:
            return url_for(endpoint)
    return url_for("minha_senha")


def requer(*aceitas: str):
    """Exige pelo menos uma das permissões (permissoes.py). Conferido no servidor a
    cada pedido, inclusive POST: esconder a aba não basta."""
    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            perms = _permissoes_logado()
            if not perms.intersection(aceitas):
                flash("Seu grupo não tem acesso a essa página.", "erro")
                return redirect(_pagina_inicial(perms))
            return f(*args, **kwargs)
        return wrapper
    return decorador


@app.context_processor
def injetar_usuario_e_permissoes():
    cfg = config_store.carregar()
    entrada = _entrada_usuario_logado(cfg)
    perms = permissoes.do_usuario(cfg, entrada) if session.get("autenticado") else set()
    # Selo "Automáticos ok · 18:01" no topo de todas as páginas (U9).
    status = None
    if "ver_automaticos" in perms:
        status = painel_info.status_topo(access_log.listar(limite=access_log.MAX_LINHAS))
    return {
        "pode": perms,
        "usuario_e_admin": bool(entrada and entrada.get("grupo") == permissoes.GRUPO_ADMIN),
        "pagina_inicial": _pagina_inicial(perms) if perms else url_for("login"),
        "emojis": painel_info.EMOJIS,
        "status_topo": status,
    }

# Troca de porta pelo painel (reinício automático): abaixo de 1024 exige root.
PORTA_MIN = 1024


def _porta_livre(porta: int) -> bool:
    """Testa se dá pra escutar na porta (mesmo bind dual-stack do gunicorn.conf.py)."""
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("::", porta))
        return True
    except OSError:
        return False


def _sob_gunicorn() -> bool:
    return os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn")


def _recarregar_servico_em_instantes() -> None:
    """SIGHUP no master do Gunicorn: relê gunicorn.conf.py (porta nova), abre a
    escuta nova e troca o worker, sem root e sem systemctl. Espera um pouco pra
    resposta (a página "reiniciando") chegar antes."""
    master = os.getppid()
    threading.Timer(1.5, lambda: os.kill(master, signal.SIGHUP)).start()


def _endereco_com_porta(porta: int) -> str:
    host = request.host
    # Tira a porta atual do host (IPv6 entre colchetes ou nome/IPv4).
    if host.startswith("["):
        host = host[: host.index("]") + 1]
    else:
        host = host.rsplit(":", 1)[0]
    return f"{request.scheme}://{host}:{porta}/configuracoes#acesso"


# Limites do push (iguais aos maxlength dos formulários; o servidor também confere).
LIMITE_TITULO = 80
LIMITE_MENSAGEM = 500


@app.route("/login", methods=["GET", "POST"])
def login():
    cfg = config_store.carregar()
    ip = _ip_do_cliente()
    _, bloqueado_ate = _tentativas_login.get(ip, (0, 0.0))
    primeira_vez = not cfg.get("usuarios")

    if time.time() < bloqueado_ate:
        flash("Muitas tentativas erradas. Tente de novo em alguns minutos.", "erro")
        return render_template("login.html", primeira_vez=primeira_vez)

    if request.method == "POST":
        usuario = request.form.get("usuario", "")
        senha = request.form.get("senha", "")
        entrada = next(
            (u for u in cfg.get("usuarios", []) if u["username"] == usuario), None
        )
        if entrada and check_password_hash(entrada["password_hash"], senha):
            if not entrada.get("ativo", True):
                access_log.registrar("login_falha", usuario=usuario, ip=ip, detalhes="usuário bloqueado")
                flash("Usuário bloqueado. Fale com o administrador do painel.", "erro")
                return render_template("login.html", primeira_vez=primeira_vez)
            session.clear()
            session["autenticado"] = True
            session["usuario"] = usuario
            _tentativas_login.pop(ip, None)
            access_log.registrar("login_sucesso", usuario=usuario, ip=ip)
            return redirect(_pagina_inicial(permissoes.do_usuario(cfg, entrada)))

        contagem, _ = _tentativas_login.get(ip, (0, 0.0))
        contagem += 1
        bloqueio = time.time() + _BLOQUEIO_SEGUNDOS if contagem >= _MAX_TENTATIVAS else 0.0
        _tentativas_login[ip] = (contagem, bloqueio)
        access_log.registrar("login_falha", usuario=usuario, ip=ip)
        flash("Usuário ou senha incorretos.", "erro")

    return render_template("login.html", primeira_vez=primeira_vez)


@app.route("/definir-senha", methods=["POST"])
def definir_senha_inicial():
    # Só é permitido enquanto nenhum usuário tiver sido criado ainda
    # (primeiro uso do painel, se não foi feito via install.sh). Depois
    # disso, novos usuários só podem ser criados em Configurações, já
    # logado.
    cfg = config_store.carregar()
    if cfg.get("usuarios"):
        abort(403)

    usuario = request.form.get("usuario", "").strip()
    senha = request.form.get("senha", "")
    confirmacao = request.form.get("confirmacao", "")
    problemas = validar_forca_senha(senha)
    if not usuario:
        problemas.append("informe um usuário")
    if senha != confirmacao:
        problemas.append("as senhas não coincidem")

    if problemas:
        flash("Não atende aos requisitos: " + ", ".join(problemas), "erro")
        return redirect(url_for("login"))

    cfg["usuarios"] = [{
        "username": usuario,
        "password_hash": generate_password_hash(senha),
        "grupo": permissoes.GRUPO_ADMIN,
        "is_admin": True,
        "ativo": True,
    }]
    config_store.salvar(cfg)
    access_log.registrar("usuario_criado", usuario=usuario, ip=_ip_do_cliente(), detalhes="primeiro usuário (admin)")
    flash("Usuário e senha definidos com sucesso. Faça login.", "sucesso")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
@login_obrigatorio
@requer("enviar")
def dashboard():
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip() or "Aviso da HOTNET"
        corpo = request.form.get("mensagem", "").strip()
        if not corpo:
            flash("Digite uma mensagem.", "erro")
        elif len(titulo) > LIMITE_TITULO or len(corpo) > LIMITE_MENSAGEM:
            flash(f"Texto grande demais: título até {LIMITE_TITULO} e mensagem até {LIMITE_MENSAGEM} caracteres.", "erro")
        else:
            try:
                enviar_aviso(titulo, corpo)
                access_log.registrar(
                    "aviso_enviado", usuario=session.get("usuario", ""),
                    ip=_ip_do_cliente(), detalhes=titulo, mensagem=corpo,
                )
                flash(f"Aviso \u201c{titulo}\u201d enviado às {painel_info.agora_hhmm()}.", "sucesso")
                return redirect(url_for("dashboard"))
            except Exception as e:
                app.logger.exception("Falha ao enviar aviso")
                access_log.registrar(
                    "aviso_falha", usuario=session.get("usuario", ""),
                    ip=_ip_do_cliente(), detalhes=str(e),
                )
                flash(
                    "Não foi possível enviar o aviso agora. Tente de novo em "
                    "instantes; se persistir, avise o administrador (o "
                    "detalhe técnico ficou registrado em Logs).",
                    "erro",
                )

    cfg = config_store.carregar()
    eventos = access_log.listar(limite=access_log.MAX_LINHAS)
    # "Usar" na página Modelos abre aqui com o modelo já escolhido.
    modelo_inicial = request.args.get("modelo", "")
    return render_template(
        "dashboard.html",
        templates=cfg.get("templates", []),
        modelo_inicial=modelo_inicial,
        ultimos_avisos=painel_info.ultimos_avisos(eventos),
        limite_titulo=LIMITE_TITULO,
        limite_mensagem=LIMITE_MENSAGEM,
    )


@app.route("/modelos", methods=["GET", "POST"])
@login_obrigatorio
@requer("modelos")
def modelos():
    cfg = config_store.carregar()

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "criar":
            nome = request.form.get("nome", "").strip()
            titulo = request.form.get("titulo", "").strip() or "Aviso da HOTNET"
            mensagem = request.form.get("mensagem", "").strip()
            if not nome or not mensagem:
                flash("Preencha o nome do modelo e a mensagem.", "erro")
            else:
                cfg.setdefault("templates", []).append({
                    "id": uuid.uuid4().hex,
                    "nome": nome,
                    "titulo": titulo,
                    "mensagem": mensagem,
                })
                config_store.salvar(cfg)
                flash("Modelo criado com sucesso.", "sucesso")

        elif acao == "editar":
            template_id = request.form.get("id")
            nome = request.form.get("nome", "").strip()
            titulo = request.form.get("titulo", "").strip() or "Aviso da HOTNET"
            mensagem = request.form.get("mensagem", "").strip()
            if not nome or not mensagem:
                flash("Preencha o nome do modelo e a mensagem.", "erro")
            else:
                encontrado = False
                for t in cfg.get("templates", []):
                    if t.get("id") == template_id:
                        t["nome"] = nome
                        t["titulo"] = titulo
                        t["mensagem"] = mensagem
                        encontrado = True
                        break
                if encontrado:
                    config_store.salvar(cfg)
                    flash("Modelo atualizado com sucesso.", "sucesso")
                else:
                    flash("Modelo não encontrado.", "erro")

        elif acao == "excluir":
            template_id = request.form.get("id")
            antes = len(cfg.get("templates", []))
            cfg["templates"] = [t for t in cfg.get("templates", []) if t.get("id") != template_id]
            if len(cfg["templates"]) < antes:
                config_store.salvar(cfg)
                flash("Modelo removido.", "sucesso")

        return redirect(url_for("modelos"))

    return render_template("modelos.html", templates=cfg.get("templates", []))


@app.route("/automaticos", methods=["GET", "POST"])
@login_obrigatorio
@requer("ver_automaticos")
def automaticos():
    """Notificações que o poller manda sozinho: funcionamento, contagem do dia e
    lembretes (antecedência e horário). Alterar exige a permissão "lembretes"."""
    cfg = config_store.carregar()

    if request.method == "POST":
        if "lembretes" not in _permissoes_logado():
            flash("Seu grupo não pode alterar os lembretes.", "erro")
            return redirect(url_for("automaticos"))
        novo, erro = lembretes.validar_formulario(
            request.form.get("dias_antes"),
            request.form.get("inicio", ""),
            request.form.get("fim", ""),
            request.form.get("atraso_ativo", ""),
        )
        if erro:
            flash("Lembretes não salvos: " + erro + ".", "erro")
        else:
            cfg["lembretes"] = novo
            config_store.salvar(cfg)
            access_log.registrar(
                "lembretes_alterados", usuario=session.get("usuario", ""),
                ip=_ip_do_cliente(), detalhes=lembretes.descrever(novo),
            )
            flash("Lembretes salvos: " + lembretes.descrever(novo) + ". Valem a partir do próximo ciclo, sem reiniciar nada.", "sucesso")
        return redirect(url_for("automaticos"))

    eventos = access_log.listar(limite=access_log.MAX_LINHAS)
    return render_template(
        "automaticos.html",
        poller=painel_info.status_poller(eventos),
        contagens=painel_info.contagens_hoje(eventos),
        lembretes=lembretes.normalizar(cfg.get("lembretes")),
        dias_permitidos=lembretes.DIAS_PERMITIDOS,
        desativado=lembretes.DESATIVADO,
    )


@app.route("/logs")
@login_obrigatorio
@requer("historico", "notificacoes")
def logs():
    perms = _permissoes_logado()
    eventos, envios = [], []
    if "historico" in perms:
        eventos = painel_info.eventos_para_tabela(access_log.listar(limite=access_log.MAX_LINHAS))
    falhas = sum(1 for e in eventos if "falhas" in e["categorias"].split())
    # Nome e CPF de clientes: só com a permissão "notificacoes".
    if "notificacoes" in perms:
        envios = painel_info.envios_para_tabela(envios_log.listar())
    return render_template("logs.html", eventos=eventos, total_falhas=falhas, envios=envios,
                           dias_envios=envios_log.DIAS_RETENCAO)


@app.route("/minha-senha", methods=["GET", "POST"])
@login_obrigatorio
def minha_senha():
    cfg = config_store.carregar()
    usuario_logado = session.get("usuario")
    entrada_logada = _entrada_usuario_logado(cfg)

    if request.method == "POST":
        atual = request.form.get("senha_atual", "")
        nova = request.form.get("nova_senha", "")
        confirmacao = request.form.get("confirmacao", "")
        if not entrada_logada or not check_password_hash(entrada_logada["password_hash"], atual):
            flash("Senha atual incorreta.", "erro")
        else:
            problemas = validar_forca_senha(nova)
            if nova != confirmacao:
                problemas.append("as senhas não coincidem")
            if problemas:
                flash("Não atende aos requisitos: " + ", ".join(problemas), "erro")
            else:
                entrada_logada["password_hash"] = generate_password_hash(nova)
                config_store.salvar(cfg)
                access_log.registrar("senha_alterada", usuario=usuario_logado, ip=_ip_do_cliente())
                flash("Senha atualizada com sucesso.", "sucesso")
        return redirect(url_for("minha_senha"))

    return render_template("minha_senha.html", usuario_atual=usuario_logado)


_ACOES_USUARIOS = {
    "novo_usuario", "remover_usuario", "alterar_grupo", "alternar_bloqueio",
    "salvar_grupos", "novo_grupo", "excluir_grupo",
}
_ACOES_REDE = {"porta", "acl"}
_NOMES_PERMISSOES = {p[0]: p[1] for _, itens in permissoes.SECOES for p in itens}


def _achar_usuario(cfg: dict, nome: str) -> dict | None:
    return next((u for u in cfg.get("usuarios", []) if u["username"] == nome), None)


def _grupo_existe(cfg: dict, nome: str) -> bool:
    return nome == permissoes.GRUPO_ADMIN or any(g["nome"] == nome for g in cfg.get("grupos", []))


def _ultimo_admin(cfg: dict, entrada: dict) -> bool:
    """True se tirar este usuário do Administrador deixaria o painel sem admin ativo."""
    return (entrada.get("grupo") == permissoes.GRUPO_ADMIN and entrada.get("ativo", True)
            and len(permissoes.admins_ativos(cfg)) <= 1)


def _acao_usuarios(cfg: dict, acao: str, usuario_logado: str, entrada_logada: dict, ip: str) -> None:
    def registrar(evento: str, detalhes: str) -> None:
        access_log.registrar(evento, usuario=usuario_logado, ip=ip, detalhes=detalhes)

    if acao == "novo_usuario":
        senha_confirmacao = request.form.get("senha_atual_novo_usuario", "")
        if not check_password_hash(entrada_logada["password_hash"], senha_confirmacao):
            flash("Sua senha atual está incorreta — confirmação necessária pra criar um novo usuário.", "erro")
            return
        novo_nome = request.form.get("novo_usuario_nome", "").strip()
        nova_senha = request.form.get("novo_usuario_senha", "")
        nova_confirmacao = request.form.get("novo_usuario_confirmacao", "")
        grupo = request.form.get("novo_usuario_grupo", "")
        problemas = validar_forca_senha(nova_senha)
        if not novo_nome:
            problemas.append("informe um nome de usuário")
        elif _achar_usuario(cfg, novo_nome):
            problemas.append("esse nome de usuário já existe")
        if nova_senha != nova_confirmacao:
            problemas.append("as senhas não coincidem")
        if not _grupo_existe(cfg, grupo):
            problemas.append("escolha um grupo")
        if problemas:
            flash("Não atende aos requisitos: " + ", ".join(problemas), "erro")
            return
        cfg.setdefault("usuarios", []).append({
            "username": novo_nome,
            "password_hash": generate_password_hash(nova_senha),
            "grupo": grupo,
            "is_admin": grupo == permissoes.GRUPO_ADMIN,
            "ativo": True,
        })
        config_store.salvar(cfg)
        registrar("usuario_criado", f"{novo_nome} ({grupo})")
        flash(f"Usuário \"{novo_nome}\" criado no grupo {grupo}.", "sucesso")
        return

    if acao in ("remover_usuario", "alterar_grupo", "alternar_bloqueio"):
        alvo = request.form.get("usuario", "")
        entrada_alvo = _achar_usuario(cfg, alvo)
        if not entrada_alvo:
            flash("Usuário não encontrado.", "erro")
            return
        if alvo == usuario_logado:
            flash("Você não pode remover, bloquear nem trocar o grupo do seu próprio usuário.", "erro")
            return

        if acao == "remover_usuario":
            if _ultimo_admin(cfg, entrada_alvo):
                flash("Esse é o único administrador ativo. Coloque outro usuário no grupo Administrador antes.", "erro")
                return
            cfg["usuarios"] = [u for u in cfg["usuarios"] if u["username"] != alvo]
            config_store.salvar(cfg)
            registrar("usuario_removido", alvo)
            flash(f"Usuário \"{alvo}\" removido.", "sucesso")

        elif acao == "alterar_grupo":
            novo = request.form.get("grupo", "")
            antigo = entrada_alvo.get("grupo")
            if not _grupo_existe(cfg, novo):
                flash("Grupo não encontrado.", "erro")
            elif novo == antigo:
                return
            elif _ultimo_admin(cfg, entrada_alvo):
                flash("Esse é o único administrador ativo. Coloque outro usuário no grupo Administrador antes.", "erro")
            else:
                entrada_alvo["grupo"] = novo
                entrada_alvo["is_admin"] = novo == permissoes.GRUPO_ADMIN
                config_store.salvar(cfg)
                registrar("usuario_grupo_alterado", f"{alvo}: {antigo} → {novo}")
                flash(f"\"{alvo}\" agora está no grupo {novo}. Vale a partir do próximo clique dele.", "sucesso")

        else:  # alternar_bloqueio
            if entrada_alvo.get("ativo", True):
                if _ultimo_admin(cfg, entrada_alvo):
                    flash("Esse é o único administrador ativo e não pode ser bloqueado.", "erro")
                    return
                entrada_alvo["ativo"] = False
                registrar("usuario_bloqueado", alvo)
                flash(f"\"{alvo}\" bloqueado. A sessão dele, se aberta, cai no próximo clique.", "sucesso")
            else:
                entrada_alvo["ativo"] = True
                registrar("usuario_desbloqueado", alvo)
                flash(f"\"{alvo}\" desbloqueado.", "sucesso")
            config_store.salvar(cfg)
        return

    grupos = cfg.setdefault("grupos", [])
    if acao == "salvar_grupos":
        # Caixas marcadas chegam como "<índice>:<permissão>"; o índice aponta para os
        # nomes enviados em "grupo_nome", na ordem em que a tabela foi desenhada.
        nomes = request.form.getlist("grupo_nome")
        marcadas: dict[str, list[str]] = {nome: [] for nome in nomes}
        for valor in request.form.getlist("perm"):
            indice, _, perm = valor.partition(":")
            if indice.isdigit() and int(indice) < len(nomes):
                marcadas[nomes[int(indice)]].append(perm)
        mudancas = []
        for g in grupos:
            if g["nome"] not in marcadas:
                continue
            limpas = permissoes.limpar(marcadas[g["nome"]])
            if limpas != g.get("permissoes"):
                g["permissoes"] = limpas
                lista = ", ".join(_NOMES_PERMISSOES[p] for p in limpas) or "nenhuma"
                mudancas.append(f"{g['nome']}: {lista}")
        if mudancas:
            config_store.salvar(cfg)
            registrar("permissoes_alteradas", "; ".join(mudancas))
            flash("Permissões salvas. Valem a partir do próximo clique de cada usuário.", "sucesso")
        else:
            flash("Nenhuma permissão mudou.", "sucesso")

    elif acao == "novo_grupo":
        nome = request.form.get("nome_grupo", "").strip()
        erro = permissoes.validar_nome(nome, grupos)
        if erro:
            flash(f"Grupo não criado: {erro}.", "erro")
            return
        base = request.form.get("base_grupo", "")
        if base == permissoes.GRUPO_ADMIN:
            perms = permissoes.limpar(permissoes.TODAS)
        else:
            origem = next((g for g in grupos if g["nome"] == base), None)
            perms = list(origem["permissoes"]) if origem else []
        grupos.append({"nome": nome, "permissoes": perms})
        config_store.salvar(cfg)
        registrar("grupo_criado", nome + (f" (cópia de {base})" if base else ""))
        flash(f"Grupo {nome} criado. Ajuste as permissões na tabela e salve.", "sucesso")

    elif acao == "excluir_grupo":
        nome = request.form.get("nome_grupo", "")
        if any(u.get("grupo") == nome for u in cfg.get("usuarios", [])):
            flash(f"O grupo {nome} tem usuários. Mova-os para outro grupo antes de excluir.", "erro")
        elif not any(g["nome"] == nome for g in grupos):
            flash("Grupo não encontrado.", "erro")
        else:
            cfg["grupos"] = [g for g in grupos if g["nome"] != nome]
            config_store.salvar(cfg)
            registrar("grupo_excluido", nome)
            flash(f"Grupo {nome} excluído.", "sucesso")


@app.route("/configuracoes", methods=["GET", "POST"])
@login_obrigatorio
@requer("usuarios", "rede")
def configuracoes():
    cfg = config_store.carregar()
    usuario_logado = session.get("usuario")
    entrada_logada = _entrada_usuario_logado(cfg)
    perms = permissoes.do_usuario(cfg, entrada_logada)
    ip = _ip_do_cliente()

    if request.method == "POST":
        acao = request.form.get("acao")
        exigida = "usuarios" if acao in _ACOES_USUARIOS else "rede" if acao in _ACOES_REDE else None
        if exigida is None or exigida not in perms:
            flash("Seu grupo não pode fazer essa alteração.", "erro")
            return redirect(url_for("configuracoes"))

        if exigida == "usuarios":
            _acao_usuarios(cfg, acao, usuario_logado, entrada_logada, ip)

        elif acao == "porta":
            try:
                nova_porta = int(request.form.get("porta", ""))
            except ValueError:
                nova_porta = 0
            porta_atual = cfg.get("port", config_store.DEFAULT_PORT)
            if not (PORTA_MIN <= nova_porta <= 65535):
                # Abaixo de 1024 o serviço (sem root) não consegue escutar e ficaria fora do ar.
                flash(f"Porta inválida: use um número entre {PORTA_MIN} e 65535.", "erro")
            elif nova_porta == porta_atual:
                flash(f"O painel já está na porta {nova_porta}.", "sucesso")
            elif not _porta_livre(nova_porta):
                flash(f"A porta {nova_porta} já está em uso por outro programa neste servidor. Escolha outra.", "erro")
            else:
                cfg["port"] = nova_porta
                config_store.salvar(cfg)
                access_log.registrar(
                    "porta_alterada", usuario=usuario_logado, ip=ip,
                    detalhes=f"{porta_atual} → {nova_porta}",
                )
                if _sob_gunicorn():
                    _recarregar_servico_em_instantes()
                    return render_template(
                        "reiniciando.html",
                        nova_porta=nova_porta,
                        novo_endereco=_endereco_com_porta(nova_porta),
                    )
                flash(
                    f"Porta salva como {nova_porta}. Este painel não roda pelo serviço, então "
                    f"reinicie-o à mão para aplicar.",
                    "sucesso",
                )

        elif acao == "acl":
            bruto = request.form.get("allowed_ips", "")
            ips = [linha.strip() for linha in bruto.splitlines() if linha.strip()]
            invalidos = []
            for faixa in ips:
                try:
                    ipaddress.ip_network(faixa, strict=False)
                except ValueError:
                    invalidos.append(faixa)
            if invalidos:
                flash("IPs/faixas inválidos: " + ", ".join(invalidos), "erro")
            else:
                cfg["allowed_ips"] = ips
                config_store.salvar(cfg)
                access_log.registrar(
                    "ips_alterados", usuario=usuario_logado, ip=ip,
                    detalhes=", ".join(ips) or "sem restrição",
                )
                flash("Lista de IPs permitidos atualizada.", "sucesso")

        if acao in _ACOES_REDE:
            secao = "acesso"
        elif acao in ("salvar_grupos", "novo_grupo", "excluir_grupo"):
            secao = "grupos"
        else:
            secao = "usuarios"
        return redirect(url_for("configuracoes", _anchor=secao))

    usuarios = cfg.get("usuarios", [])
    grupos = cfg.get("grupos", [])
    contagem = {g: sum(1 for u in usuarios if u.get("grupo") == g)
                for g in [permissoes.GRUPO_ADMIN] + [x["nome"] for x in grupos]}
    return render_template(
        "settings.html",
        usuario_atual=usuario_logado,
        usuarios=usuarios,
        grupos=grupos,
        contagem_grupos=contagem,
        secoes=permissoes.SECOES,
        so_admin=permissoes.SO_ADMIN,
        grupo_admin=permissoes.GRUPO_ADMIN,
        grupo_padrao=permissoes.GRUPO_PADRAO,
        porta_atual=cfg.get("port", config_store.DEFAULT_PORT),
        allowed_ips="\n".join(cfg.get("allowed_ips") or []),
    )


if __name__ == "__main__":
    cfg = config_store.carregar()
    app.run(host="0.0.0.0", port=cfg.get("port", config_store.DEFAULT_PORT))
