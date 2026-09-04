# Aviso Broadcaster

Painel web simples pra disparar avisos gerais (manutenção programada,
instabilidade na rede) como notificação push pra todos os usuários do
app HOTNET, via Firebase Cloud Messaging (tópico `avisos_gerais`).

## 1. Gerar a chave da conta de serviço do Firebase

Este servidor precisa de credenciais de **administrador** do Firebase
(diferente do `google-services.json` do app Android):

1. Acesse o [Firebase Console](https://console.firebase.google.com/) e
   abra o projeto do HOTNET (`apphotnet`).
2. Clique na engrenagem → **Configurações do projeto** → aba
   **Contas de serviço**.
3. Clique em **Gerar nova chave privada** e confirme.
4. Renomeie o arquivo baixado para `service-account.json` e coloque
   nesta pasta (`server/aviso-broadcaster/service-account.json`).

Esse arquivo é secreto (dá acesso de admin ao projeto Firebase) —
**nunca** o versione no git (já está no `.gitignore`).

## 2. Instalar no servidor Debian (recomendado: `install.sh`)

Copie a pasta inteira `aviso-broadcaster/` (com o `service-account.json`
já dentro, se já tiver gerado) pro servidor Debian, e rode como root:

```bash
./install.sh
```

O script:
- instala as dependências do sistema (`python3-venv`);
- cria o usuário de sistema `aviso-broadcaster` (sem shell/login);
- copia os arquivos pra `/opt/aviso-broadcaster` e cria o ambiente
  virtual Python com as dependências;
- **pergunta o usuário e a senha** de acesso ao painel (a senha exige
  mínimo 8 caracteres, maiúscula, minúscula, número e caractere
  especial — o script já valida antes de aceitar);
- pergunta a porta do painel (padrão 8765);
- instala e inicia o serviço systemd.

Ao final, ele mostra o endereço do painel e o usuário criado.

### Alternativa: instalação manual

Se preferir não rodar o `install.sh` (ou estiver noutra distro):

Execute como root (ex: `su -`):

```bash
apt update && apt install -y python3-venv

useradd --system --create-home --shell /usr/sbin/nologin aviso-broadcaster
mkdir -p /opt/aviso-broadcaster
cp -r app.py config_store.py security.py fcm_sender.py templates \
    requirements.txt gunicorn.conf.py service-account.json /opt/aviso-broadcaster/
chown -R aviso-broadcaster:aviso-broadcaster /opt/aviso-broadcaster

cd /opt/aviso-broadcaster
su -s /bin/bash aviso-broadcaster -c "python3 -m venv venv"
su -s /bin/bash aviso-broadcaster -c "venv/bin/pip install -r requirements.txt"

cp aviso-broadcaster.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now aviso-broadcaster
```

Nesse caso, o `config.json` é criado sozinho na primeira execução
(porta padrão 8765, sem usuário/senha definidos) e o primeiro acesso ao
painel via navegador vai pedir pra você **definir o usuário e a senha**
diretamente na tela de login.

## 3. Primeiro acesso

1. Abra `http://SEU_SERVIDOR:PORTA` no navegador (a porta que você
   escolheu no `install.sh`, ou 8765 por padrão).
2. Entre com o usuário e a senha que você definiu (via `install.sh` ou
   pela tela de primeiro acesso).
3. Vá em **Configurações** e cadastre pelo menos o seu próprio IP (ou
   a faixa da sua rede/VPN) na lista de IPs permitidos — por padrão,
   sem essa lista, qualquer IP consegue acessar a tela de login. Aceita
   IPv4 e IPv6 (o Gunicorn escuta em `[::]`, que no Debian já responde
   pelos dois automaticamente — não precisa configurar nada a mais).
4. Se quiser mudar a porta depois, salve o novo valor em Configurações
   e rode `systemctl restart aviso-broadcaster` (a porta só é lida na
   inicialização do processo).
5. Pra dar acesso a mais pessoas, use "Adicionar novo usuário" em
   Configurações (pede sua própria senha atual como confirmação). Não
   dá pra remover a si mesmo nem o último usuário restante, pra evitar
   ficar todo mundo trancado pra fora. **A página de Configurações
   (porta, IPs, gerenciar usuários) só fica visível e acessível pra
   quem é o usuário administrador** (o primeiro criado, marcado como
   "admin" na lista) — os demais usuários só veem as abas "Enviar
   aviso", "Modelos", "Logs" e "Minha senha".
6. Qualquer usuário (admin ou não) troca a própria senha em
   "Minha senha", sem precisar de acesso a Configurações.

## 4. Importante — use HTTPS na frente

Esse servidor roda em HTTP simples, o que significa que a senha viaja
sem criptografia entre o seu navegador e o servidor. Recomendado
fortemente colocar um proxy reverso com **HTTPS (Let's Encrypt/certbot)**
na frente dessa porta, especialmente se o servidor for acessível pela
internet (e não só pela sua rede interna/VPN) — pode ser Nginx ou, como
já é o caso da instalação atual, **Apache**.

Exemplo mínimo de `VirtualHost` do Apache fazendo proxy pra esse painel
(ajuste a porta pro valor configurado em Configurações):

```apache
<VirtualHost *:443>
    ServerName SEU_DOMINIO

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8765/
    ProxyPassReverse / http://127.0.0.1:8765/
    RequestHeader set X-Forwarded-Proto "https"

    SSLEngine on
    # ... SSLCertificateFile / SSLCertificateKeyFile (certbot) ...
</VirtualHost>
```

O `mod_proxy` do Apache já envia `X-Forwarded-For` sozinho (é assim que
a lista de IPs permitidos em Configurações identifica o IP real do
cliente); o `X-Forwarded-Proto` acima **precisa** ser configurado à mão
(diferente do Nginx, o Apache não manda esse cabeçalho por padrão).

Com o Apache terminando HTTPS, ligue o cookie de sessão como *secure*
definindo a variável de ambiente `AVISO_BROADCASTER_HTTPS=1` no serviço
systemd (edite `/etc/systemd/system/aviso-broadcaster.service`,
adicione `Environment="AVISO_BROADCASTER_HTTPS=1"` na seção `[Service]`
e rode `systemctl daemon-reload && systemctl restart aviso-broadcaster`).
Sem isso, o cookie continua funcionando normalmente, só sem essa camada
extra de proteção — não ative se o Apache ainda não tiver HTTPS
configurado, senão o login para de funcionar (o navegador não manda o
cookie de volta por HTTP).

Todo formulário do painel (login, envio de aviso, modelos, usuários,
configurações) tem proteção contra CSRF (`Flask-WTF`) — se aparecer o
aviso "Sessão expirada ou formulário inválido", geralmente é sessão
antiga (aba ficou aberta por muito tempo) ou back/forward do navegador;
é só tentar de novo.

## 5. Enviar um aviso

Depois de logado, a tela inicial já é o formulário de envio: título
(opcional) + mensagem, com opção de escolher um **modelo pronto**
(gerenciado na aba "Modelos") em vez de escrever do zero toda vez. O
botão fica desabilitado durante o envio, pra evitar clique duplo
mandando o aviso duas vezes. Ao enviar, todo cliente com o app
instalado e conectado à internet recebe a notificação em poucos
segundos. Se o envio falhar (ex: Firebase fora do ar), a tela mostra um
aviso genérico e o detalhe técnico fica registrado na aba "Logs".

A aba **"Logs"** mostra o histórico de login (sucesso/falha), avisos
enviados (e falhas de envio), e alterações de usuário — os últimos 500
eventos, guardados localmente em `acessos.log` (não versionado no
git). Tem um campo de busca no topo pra filtrar por usuário, IP ou tipo
de evento.

## 6. Atualizando uma instalação já existente

Se você já rodou o `install.sh` antes (e o serviço já está no ar), **não
precisa reinstalar do zero**. Pra pegar as atualizações mais recentes
(troca do servidor de desenvolvimento do Flask pelo Gunicorn, aba de
Modelos, etc.):

Execute como root:

```bash
systemctl stop aviso-broadcaster

# copie os arquivos atualizados por cima (mantém config.json e
# service-account.json que já estão lá, não sobrescreve)
cp app.py config_store.py security.py fcm_sender.py gunicorn.conf.py \
    requirements.txt /opt/aviso-broadcaster/
cp -r templates /opt/aviso-broadcaster/

su -s /bin/bash aviso-broadcaster -c \
    "/opt/aviso-broadcaster/venv/bin/pip install -r /opt/aviso-broadcaster/requirements.txt"

cp aviso-broadcaster.service /etc/systemd/system/
systemctl daemon-reload
systemctl start aviso-broadcaster
systemctl status aviso-broadcaster
```

O `config.json` se atualiza sozinho: ganha a chave de modelos
(`templates`) e migra o usuário/senha único de versões antigas pra uma
lista de usuários (`usuarios`), sem apagar nada que já estava
configurado (porta, IPs, senha do usuário original).

## 7. Desinstalar

```bash
./uninstall.sh
```

Pede confirmação e remove o serviço systemd, a pasta `/opt/aviso-broadcaster`
inteira (config.json e service-account.json incluídos) e o usuário de
sistema `aviso-broadcaster`.

## 8. Identidade visual

O visual do painel foi alinhado ao do app HOTNET (`WEB_APPS/HOTNET_WEB_APP`):

- **Fonte:** Plus Jakarta Sans (mesma do web app), carregada via Google
  Fonts.
- **Cores de marca:** o laranja/vermelho do gradiente (`#F28F3B` →
  `#D94A38`) já é o mesmo `--cor-primaria`/`--cor-primaria-escura` usado
  lá — não precisou trocar.
- **Tema claro/escuro:** segue a preferência do sistema operacional por
  padrão, com um botão no cabeçalho (🌙/☀️) pra alternar manualmente —
  a escolha fica salva no navegador (`localStorage`), mesmo padrão de
  `src/utils/tema.ts` do web app. Paleta escura reaproveita os mesmos
  tons de `src/index.css` (`#121316` fundo, `#1e2025` superfície, etc).
- **Mostrar/ocultar senha:** todo campo de senha do painel ganha um
  ícone de olho pra revelar o texto digitado (aplicado automaticamente
  via JS em `base.html`, não precisa repetir por template).
- **Microinterações:** fade-in leve ao carregar a página e um
  "afundar" sutil (scale) ao clicar em botões, no mesmo espírito do
  feedback de toque do web app; tudo respeita
  `prefers-reduced-motion`.

Todo o CSS mora num único bloco `<style>` em `templates/base.html`,
como variáveis (`--cor-*`, `--raio`, `--sombra`) no `:root` — é ali que
se ajusta qualquer cor, raio de borda ou sombra do painel inteiro.

## 9. Poller de confirmação de pagamento (piloto)

Peça separada do painel web, sem interface própria ainda: consulta o
Controllr periodicamente (como um admin, não como cliente) e manda push
individual só pra conta que teve uma fatura paga — diferente do
`avisos_gerais`, que vai pra todo mundo. Não altera nada no Controllr,
só lê (`invoice_ctl/invoice/list`) com um usuário dedicado.

**Por que existe**: o Controllr não tem webhook/push próprio, então "em
tempo real" aqui significa "checagem periódica" (a cada 10min, por
padrão) — o poller guarda o que já viu em `poller_state.json` e só
notifica na transição de "sem data de crédito" pra "com data de
crédito", nunca de novo pra quem já foi notificado.

### Como identifica a conta

O app assina, no login, o tópico FCM `conta_<hash>` — hash SHA-256 (16
primeiros caracteres hex) do CPF só com dígitos (ver `topico_conta_cpf()`
em `poller.py` e o equivalente em `SessionManager.kt` no app Android).
Nunca é o CPF cru — evita expor PII no nome do tópico.

### Configuração

1. No Controllr, crie um usuário admin **dedicado, só leitura** pra essa
   função (não reaproveite login pessoal).
2. Rode `python poller.py` uma vez manualmente — ele cria
   `controllr_config.json` com um template e para, avisando o que
   falta preencher (`base_url` da área **administrativa**, porta
   8080/8081/8443 conforme configurado no Controllr — não é a mesma
   porta 443 que o app Android usa; `usuario`; `senha`). Validado em
   produção: `https://controllr.hotnet.net.br:8443/` — atenção ao
   `.net.br`, sem ele o domínio não resolve.
3. Preencha o arquivo e rode `python poller.py` **manualmente** de novo
   — essa primeira execução real só grava a baseline (nenhuma
   notificação é enviada nela, mesmo que existam milhares de faturas já
   pagas na janela — ver comentário em `poller.py`). Confirme pela aba
   Logs (`poller_ciclo`, "baseline gravada") antes de seguir.
4. Só depois da baseline gravada, instale como serviço + timer do
   systemd:

```bash
cp controllr-poller.service controllr-poller.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now controllr-poller.timer
```

5. Acompanhe pela aba **Logs** do painel (eventos `poller_ciclo` e
   `poller_falha`) — reaproveita o mesmo `access_log.py` dos outros
   eventos.

Pra mudar o intervalo (padrão 10min): edite `OnUnitActiveSec` em
`controllr-poller.timer`, depois `systemctl daemon-reload && systemctl restart controllr-poller.timer`.

`controllr_config.json` e `poller_state.json` seguem o mesmo padrão de
`config.json`/`service-account.json`: nunca versionados no git,
permissão `600`.

**Status**: piloto — só confirmação de pagamento. Lado do Controllr
(login admin, busca em lote, campos usados) já validado contra produção;
falta só validar o push chegando de fato no aparelho depois do deploy.
Chamado de suporte atualizado e reforço de fatura em atraso ficam de
fora até esse validar bem em produção.
