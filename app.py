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
import config_store
import lembretes
import painel_info
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
        return f(*args, **kwargs)
    return wrapper


def _entrada_usuario_logado(cfg: dict) -> dict | None:
    usuario_logado = session.get("usuario")
    return next(
        (u for u in cfg.get("usuarios", []) if u["username"] == usuario_logado), None
    )


def admin_obrigatorio(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        cfg = config_store.carregar()
        entrada = _entrada_usuario_logado(cfg)
        if not entrada or not entrada.get("is_admin"):
            flash("Apenas o administrador tem acesso a essa página.", "erro")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def injetar_usuario_e_admin():
    cfg = config_store.carregar()
    entrada = _entrada_usuario_logado(cfg)
    # Selo "Automáticos ok · 18:01" no topo de todas as páginas (U9).
    status = None
    if session.get("autenticado"):
        status = painel_info.status_topo(access_log.listar(limite=access_log.MAX_LINHAS))
    return {
        "usuario_e_admin": bool(entrada and entrada.get("is_admin")),
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
            session["autenticado"] = True
            session["usuario"] = usuario
            _tentativas_login.pop(ip, None)
            access_log.registrar("login_sucesso", usuario=usuario, ip=ip)
            return redirect(url_for("dashboard"))

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
        "is_admin": True,
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
def automaticos():
    """Notificações que o poller manda sozinho: funcionamento, contagem do dia e
    lembretes (antecedência e horário). Todos veem; só o admin altera."""
    cfg = config_store.carregar()
    entrada = _entrada_usuario_logado(cfg)
    e_admin = bool(entrada and entrada.get("is_admin"))

    if request.method == "POST":
        if not e_admin:
            flash("Apenas o administrador pode alterar os lembretes.", "erro")
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
def logs():
    eventos = painel_info.eventos_para_tabela(access_log.listar(limite=access_log.MAX_LINHAS))
    falhas = sum(1 for e in eventos if "falhas" in e["categorias"].split())
    return render_template("logs.html", eventos=eventos, total_falhas=falhas)


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


@app.route("/configuracoes", methods=["GET", "POST"])
@login_obrigatorio
@admin_obrigatorio
def configuracoes():
    cfg = config_store.carregar()
    usuario_logado = session.get("usuario")
    entrada_logada = _entrada_usuario_logado(cfg)

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "novo_usuario":
            senha_confirmacao = request.form.get("senha_atual_novo_usuario", "")
            if not entrada_logada or not check_password_hash(entrada_logada["password_hash"], senha_confirmacao):
                flash("Sua senha atual está incorreta — confirmação necessária pra criar um novo usuário.", "erro")
            else:
                novo_nome = request.form.get("novo_usuario_nome", "").strip()
                nova_senha = request.form.get("novo_usuario_senha", "")
                nova_confirmacao = request.form.get("novo_usuario_confirmacao", "")
                problemas = validar_forca_senha(nova_senha)
                if not novo_nome:
                    problemas.append("informe um nome de usuário")
                elif any(u["username"] == novo_nome for u in cfg.get("usuarios", [])):
                    problemas.append("esse nome de usuário já existe")
                if nova_senha != nova_confirmacao:
                    problemas.append("as senhas não coincidem")
                if problemas:
                    flash("Não atende aos requisitos: " + ", ".join(problemas), "erro")
                else:
                    cfg.setdefault("usuarios", []).append({
                        "username": novo_nome,
                        "password_hash": generate_password_hash(nova_senha),
                        "is_admin": False,
                    })
                    config_store.salvar(cfg)
                    access_log.registrar(
                        "usuario_criado", usuario=usuario_logado,
                        ip=_ip_do_cliente(), detalhes=novo_nome,
                    )
                    flash(f"Usuário \"{novo_nome}\" criado com sucesso.", "sucesso")

        elif acao == "remover_usuario":
            alvo = request.form.get("usuario_remover", "")
            entrada_alvo = next(
                (u for u in cfg.get("usuarios", []) if u["username"] == alvo), None
            )
            if entrada_alvo and entrada_alvo.get("is_admin"):
                flash("Não é possível remover o usuário administrador principal.", "erro")
            elif len(cfg.get("usuarios", [])) <= 1:
                flash("Não é possível remover o único usuário existente.", "erro")
            elif alvo == usuario_logado:
                flash("Você não pode remover seu próprio usuário enquanto estiver logado com ele.", "erro")
            else:
                antes = len(cfg.get("usuarios", []))
                cfg["usuarios"] = [u for u in cfg.get("usuarios", []) if u["username"] != alvo]
                if len(cfg["usuarios"]) < antes:
                    config_store.salvar(cfg)
                    access_log.registrar(
                        "usuario_removido", usuario=usuario_logado,
                        ip=_ip_do_cliente(), detalhes=alvo,
                    )
                    flash(f"Usuário \"{alvo}\" removido.", "sucesso")

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
                    "porta_alterada", usuario=usuario_logado, ip=_ip_do_cliente(),
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
            for ip in ips:
                try:
                    ipaddress.ip_network(ip, strict=False)
                except ValueError:
                    invalidos.append(ip)
            if invalidos:
                flash("IPs/faixas inválidos: " + ", ".join(invalidos), "erro")
            else:
                cfg["allowed_ips"] = ips
                config_store.salvar(cfg)
                flash("Lista de IPs permitidos atualizada.", "sucesso")

        secao = "acesso" if acao in ("porta", "acl") else "usuarios"
        return redirect(url_for("configuracoes", _anchor=secao))

    return render_template(
        "settings.html",
        usuario_atual=session.get("usuario", ""),
        usuarios=cfg.get("usuarios", []),
        porta_atual=cfg.get("port", config_store.DEFAULT_PORT),
        allowed_ips="\n".join(cfg.get("allowed_ips") or []),
    )


if __name__ == "__main__":
    cfg = config_store.carregar()
    app.run(host="0.0.0.0", port=cfg.get("port", config_store.DEFAULT_PORT))
