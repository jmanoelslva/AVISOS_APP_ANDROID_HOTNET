import ipaddress
import time
import uuid
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import access_log
import config_store
from fcm_sender import enviar_aviso
from security import validar_forca_senha

app = Flask(__name__)
app.secret_key = config_store.carregar()["secret_key"]

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
    return {"usuario_e_admin": bool(entrada and entrada.get("is_admin"))}


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
        else:
            try:
                enviar_aviso(titulo, corpo)
                access_log.registrar(
                    "aviso_enviado", usuario=session.get("usuario", ""),
                    ip=_ip_do_cliente(), detalhes=titulo,
                )
                flash("Aviso enviado com sucesso!", "sucesso")
            except Exception as e:
                flash(f"Erro ao enviar: {e}", "erro")

    cfg = config_store.carregar()
    return render_template("dashboard.html", templates=cfg.get("templates", []))


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


@app.route("/logs")
@login_obrigatorio
def logs():
    return render_template("logs.html", eventos=access_log.listar())


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
                if not (1 <= nova_porta <= 65535):
                    raise ValueError
                cfg["port"] = nova_porta
                config_store.salvar(cfg)
                flash(
                    f"Porta salva como {nova_porta}. Reinicie o serviço pra aplicar: "
                    f"systemctl restart aviso-broadcaster",
                    "sucesso",
                )
            except ValueError:
                flash("Porta inválida — use um número entre 1 e 65535.", "erro")

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

        return redirect(url_for("configuracoes"))

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
