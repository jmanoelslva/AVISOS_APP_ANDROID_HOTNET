import json
import os
import secrets
import uuid
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULT_PORT = 8765

_config_cache = None


def _templates_padrao() -> list[dict]:
    return [
        {
            "id": uuid.uuid4().hex,
            "nome": "Manutenção programada",
            "titulo": "Manutenção programada na rede",
            "mensagem": (
                "Informamos que realizaremos uma manutenção programada em nossa "
                "rede hoje, das 23h às 01h. Durante esse período, sua conexão "
                "pode apresentar instabilidade ou ficar temporariamente "
                "indisponível."
            ),
        },
        {
            "id": uuid.uuid4().hex,
            "nome": "Instabilidade na rede",
            "titulo": "Instabilidade em nossa rede",
            "mensagem": (
                "Identificamos uma instabilidade em nossa rede que pode estar "
                "afetando sua conexão. Nossa equipe técnica já está atuando "
                "para normalizar o quanto antes. Pedimos desculpas pelo "
                "transtorno."
            ),
        },
        {
            "id": uuid.uuid4().hex,
            "nome": "Rede normalizada",
            "titulo": "Conexão normalizada",
            "mensagem": (
                "A instabilidade identificada anteriormente em nossa rede já "
                "foi corrigida e sua conexão deve estar funcionando "
                "normalmente. Caso ainda apresente problemas, entre em "
                "contato com nosso suporte."
            ),
        },
        {
            "id": uuid.uuid4().hex,
            "nome": "Lentidão temporária",
            "titulo": "Lentidão temporária na rede",
            "mensagem": (
                "Nossa rede está passando por uma lentidão temporária devido "
                "a um alto volume de acessos. Estamos trabalhando para "
                "normalizar a velocidade da sua conexão o mais rápido "
                "possível."
            ),
        },
        {
            "id": uuid.uuid4().hex,
            "nome": "Interrupção por causa externa",
            "titulo": "Interrupção na conexão",
            "mensagem": (
                "Sua conexão pode estar indisponível devido a uma "
                "interrupção causada por fatores externos à nossa rede (ex: "
                "rompimento de fibra ou falta de energia na região). Nossa "
                "equipe já foi acionada e estamos trabalhando para "
                "restabelecer o quanto antes."
            ),
        },
    ]


def _gerar_config_padrao() -> dict:
    return {
        "usuarios": [],  # lista de {"username": ..., "password_hash": ...}
        "port": DEFAULT_PORT,
        "allowed_ips": [],
        "secret_key": secrets.token_hex(32),
        "templates": [],
        "templates_seed_aplicado": False,
    }


def carregar() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if not CONFIG_PATH.exists():
        _config_cache = _gerar_config_padrao()
        _config_cache["templates"] = _templates_padrao()
        _config_cache["templates_seed_aplicado"] = True
        salvar(_config_cache)
    else:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _config_cache = json.load(f)
        # Preenche chaves novas em configs já existentes (de uma versão
        # anterior do painel) sem mexer no que já estava configurado.
        alterou = False
        for chave, valor in _gerar_config_padrao().items():
            if chave not in _config_cache:
                _config_cache[chave] = valor
                alterou = True
        # Semeia os 5 modelos prontos só uma vez — se o cliente já tinha
        # instalado antes (config antigo, sem essa chave) ou nunca criou
        # nenhum modelo ainda. Depois disso o flag garante que apagar os
        # modelos de propósito não os traz de volta sozinho.
        if not _config_cache.get("templates_seed_aplicado"):
            if not _config_cache.get("templates"):
                _config_cache["templates"] = _templates_padrao()
            _config_cache["templates_seed_aplicado"] = True
            alterou = True
        # Migra o usuário único (versões anteriores, com "username" e
        # "password_hash" soltos) pra dentro da lista "usuarios" — feito
        # uma vez só, já que depois disso as chaves antigas são removidas.
        if "username" in _config_cache or "password_hash" in _config_cache:
            usuario_antigo = _config_cache.get("username")
            hash_antigo = _config_cache.get("password_hash")
            if usuario_antigo and hash_antigo:
                ja_existe = any(
                    u["username"] == usuario_antigo for u in _config_cache.get("usuarios", [])
                )
                if not ja_existe:
                    _config_cache.setdefault("usuarios", []).append({
                        "username": usuario_antigo,
                        "password_hash": hash_antigo,
                    })
            _config_cache.pop("username", None)
            _config_cache.pop("password_hash", None)
            alterou = True
        if alterou:
            salvar(_config_cache)
    return _config_cache


def salvar(config: dict) -> None:
    global _config_cache
    _config_cache = config
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    # Contém o hash da senha e a secret key de sessão — só o dono do
    # processo precisa conseguir ler.
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
