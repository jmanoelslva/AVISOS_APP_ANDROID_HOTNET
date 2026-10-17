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
- copia os arquivos pra `/opt/aviso-broadcaster` (painel **e** poller) e
  cria o ambiente virtual Python com as dependências;
- **pergunta o usuário e a senha** de acesso ao painel (a senha exige
  mínimo 8 caracteres, maiúscula, minúscula, número e caractere
  especial — o script já valida antes de aceitar);
- pergunta a porta do painel (padrão 8765);
- **pergunta o domínio (opcional)**. Com domínio, chama o
  `configurar-dominio.sh` (seção 4): HTTPS com Let's Encrypt e renovação
  automática. Sem domínio, o acesso é por `http://IP:PORTA`;
- instala e inicia o serviço systemd do painel;
- **pergunta se quer configurar o poller de eventos por conta** (opcional
  — pagamento confirmado, chamado atualizado, fatura atrasada, ver
  seção 9): se sim, pede a URL/usuário/senha do admin dedicado do
  Controllr, roda a primeira execução (baseline, não notifica ninguém)
  e só instala o timer systemd se essa execução funcionar. Se der
  errado (URL/credencial erradas), o script avisa e não instala o
  timer, sem travar o resto da instalação.

Se copiar a pasta inteira do repo (recomendado — inclui `install.sh` e
todos os arquivos que ele espera), não copie `config.json`,
`controllr_config.json`, `poller_state.json` ou `acessos.log` de uma
instalação/máquina de teste antiga — são estado local de cada instância,
não fazem parte do código.

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
3. Vá em **Ajustes** e cadastre pelo menos o seu próprio IP (ou
   a faixa da sua rede/VPN) na lista de IPs permitidos — por padrão,
   sem essa lista, qualquer IP consegue acessar a tela de login. Aceita
   IPv4 e IPv6 (o Gunicorn escuta em `[::]`, que no Debian já responde
   pelos dois automaticamente — não precisa configurar nada a mais).
4. Para mudar a porta depois, use **Ajustes → Acesso e rede → Salvar e
   aplicar** (1024 a 65535). O painel manda SIGHUP para o Gunicorn, que relê
   `gunicorn.conf.py` e passa a escutar na porta nova, sem root nem
   `systemctl`; a página leva ao endereço novo. Libere a porta no firewall
   antes. Se algo der errado, edite `port` em `config.json` e rode
   `systemctl restart aviso-broadcaster`.
5. **Usuários e grupos** (Ajustes). Cada usuário pertence a um grupo, e o
   grupo define o que ele vê e altera:

   | Permissão | O que libera |
   |---|---|
   | Enviar aviso geral | Aba Enviar |
   | Gerenciar modelos | Aba Modelos (criar, editar, excluir) |
   | Ver automáticos | Aba Automáticos, só leitura |
   | Alterar lembretes | Salvar os lembretes em Automáticos (inclui Ver automáticos) |
   | Ver histórico de eventos | Histórico: logins, avisos, alterações, ciclos |
   | Ver notificações de clientes | Histórico → Notificações (nome, CPF/CNPJ, valores) |
   | Alterar porta e IPs permitidos | Ajustes → Acesso e rede |
   | Gerenciar usuários e grupos | Ajustes → Usuários e Grupos (só Administrador) |

   - **Administrador** é fixo: tem todas as permissões, não é editável e
     precisa ter pelo menos um usuário ativo.
   - **Atendimento** é criado na atualização para a 1.5.0 com o que os
     usuários não administradores podiam fazer antes. Pode ser editado.
   - Outros grupos: "+ Novo grupo", opcionalmente copiando as permissões de
     um existente. Grupo com usuários não pode ser excluído.
   - Abas sem permissão somem do topo; o servidor recusa o acesso mesmo por
     link direto ou formulário montado à mão.
   - **Editar** (em cada usuário): grupo, situação (ativo/bloqueado) e nova
     senha, que é opcional; em branco, mantém a atual.
   - Trocar o grupo ou as permissões vale no próximo clique do usuário.
     Trocar a senha, bloquear ou remover encerra a sessão aberta dele.
   - Ninguém edita nem remove o próprio usuário por Ajustes; a própria
     senha muda em "Minha senha", que encerra as outras sessões abertas.
   - "+ Novo usuário" e "Editar" não pedem a senha de quem está alterando.
   - **Regras da senha**, mostradas e marcadas enquanto se digita (o
     servidor confere de novo): 8 a 128 caracteres, uma letra maiúscula
     (A–Z), uma minúscula (a–z), um número (0–9) e um símbolo (qualquer
     caractere fora de A–Z, a–z e 0–9, ex.: `! @ # $ % & * - _ .`).
     "Gerar" cria uma senha aleatória de 14 caracteres.
   - Tudo fica registrado no Histórico.
   - Dados em `config.json`: `grupos` (nome e permissões) e, em cada
     usuário, `grupo` e `ativo`. `is_admin` continua gravado para permitir
     voltar à 1.4.x.
6. Qualquer usuário troca a própria senha em "Minha senha", sem precisar
   de acesso a Ajustes.

## 4. Domínio e HTTPS (opcional)

Sem domínio, o painel responde em `http://IP:PORTA` e a senha trafega sem
criptografia. Use só em rede interna/VPN, com a lista de IPs permitidos.

Com domínio, o painel fica em `https://SEU_DOMINIO`:

```bash
cd /opt/aviso-broadcaster
./configurar-dominio.sh painel.exemplo.com.br email@exemplo.com.br   # ativar
./configurar-dominio.sh --remover                                     # voltar ao IP
```

Requisitos: o domínio apontando (registro A e/ou AAAA) para este servidor e
as portas 80 e 443 liberadas. O e-mail é opcional; sem ele, o Let's Encrypt
não avisa se a renovação falhar.

O script:
- confere o DNS do domínio (avisa se não apontar para este servidor);
- usa o **Apache** se já estiver rodando no servidor; senão instala o **Nginx**;
- cria o site com proxy para `127.0.0.1:PORTA` e emite o certificado com o
  certbot, redirecionando HTTP para HTTPS. Se o certificado falhar, remove o
  site, e o painel nunca fica exposto pelo domínio só em HTTP;
- ativa a renovação automática (`certbot.timer`, duas vezes ao dia, renova
  com 30 dias de antecedência; o certbot recarrega o servidor web) e testa
  com `certbot renew --dry-run`;
- libera 80/443 no `ufw`, se ele estiver ativo;
- grava `dominio` no `config.json` e cria
  `/etc/systemd/system/aviso-broadcaster.service.d/dominio.conf` com
  `AVISO_BROADCASTER_HTTPS=1` (cookie de sessão só por HTTPS) e
  `AVISO_BROADCASTER_PROXY=1` (IP real do cliente vem do proxy);
- reinicia o painel escutando só em `127.0.0.1`: o acesso por `IP:PORTA`
  deixa de existir.

Com domínio, a porta não muda por Ajustes (ela é interna); Ajustes mostra o
endereço HTTPS. A lista de IPs permitidos continua valendo, com o IP real do
cliente.

Conferir a renovação:

```bash
systemctl list-timers certbot.timer
certbot certificates
```

**IP do cliente e lista de IPs permitidos.** O cabeçalho `X-Forwarded-For`
só é aceito com `AVISO_BROADCASTER_PROXY=1` e em conexões vindas do próprio
servidor (127.0.0.1/::1), e vale o último item, o que o proxy acrescenta.
Sem proxy, vale o IP da conexão.

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
aviso genérico e o detalhe técnico fica registrado na aba "Histórico".

A aba **"Histórico"** mostra o histórico de login (sucesso/falha), avisos
enviados (e falhas de envio), e alterações de usuário — os últimos 1000
eventos, guardados localmente em `acessos.log` (não versionado no
git). Tem um campo de busca no topo pra filtrar por usuário, IP ou tipo
de evento.

Em **Notificações** (dentro do Histórico) fica cada aviso automático do
poller com o cliente: tipo (pagamento confirmado, cobrança de atraso,
lembrete antecipado, chamado respondido), nome, CPF/CNPJ completo e o que
foi avisado (valor, vencimento, contrato ou número do chamado). Envio que
falhou aparece com o motivo. Cartões coloridos no topo contam cada tipo
no período (hoje, 7 ou 30 dias) e filtram a lista com um clique; a busca
aceita nome, CPF com ou sem pontos, contrato e número do chamado. Fica em
`envios.log` (permissão 600, fora do git), separado do `acessos.log`, e
guarda só os últimos 30 dias. Envios de teste feitos à mão, fora do
poller, não aparecem ali.

## 6. Atualizando uma instalação já existente

**Instalação feita com `git clone` direto em `/opt/aviso-broadcaster`** (o
caso do servidor atual): basta, como root,

```bash
cd /opt/aviso-broadcaster && git pull
chown -R aviso-broadcaster: /opt/aviso-broadcaster
systemctl restart aviso-broadcaster   # só o painel; o poller não precisa
```

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
    access_log.py painel_info.py requirements.txt /opt/aviso-broadcaster/
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

- **Fonte:** Manrope, a mesma do app HOTNET, servida pelo próprio painel
  (`static/fonts`, WOFF2, licença SIL OFL 1.1). Não depende do Google Fonts.
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

## 9. Poller de eventos por conta (piloto)

Peça separada do painel web, sem interface própria ainda: consulta o
Controllr periodicamente (como um admin, não como cliente) e manda push
individual só pra conta afetada — diferente do `avisos_gerais`, que vai
pra todo mundo. Não altera nada no Controllr, só lê (`invoice_ctl/invoice/list`,
`support_ctl/ticket/list`, `support_ctl/op/list`) com um usuário dedicado.

**Por que existe**: o Controllr não tem webhook/push próprio, então "em
tempo real" aqui significa "checagem periódica" (a cada 1 hora, por
padrão, para não encher o log de acesso do Controllr) — o poller guarda o que já viu em `poller_state.json`, por
categoria (`faturas`/`faturas_atrasadas`/`faturas_vence_amanha`/
`chamados`), e só notifica em cima de uma transição real, nunca de novo
pra quem já foi notificado:

- **Pagamento confirmado**: `invoice_date_credit` passa de vazio pra
  preenchido. O payload leva valor pago, contrato, vencimento e, desde a
  v1.1.0, a própria `invoice_date_credit` (o app mostra "Pago em dd/mm/aaaa").
- **Chamado atualizado**: `ticket_date_last` muda **e** a última
  operação do chamado (`support_ctl/op/list`) foi escrita pela equipe
  (`op_client=False`) — se foi o próprio cliente quem mexeu por último
  (respondeu pelo app), não notifica, senão seria um aviso sobre a
  própria ação da pessoa.
- **Fatura atrasada**: `invoice_late` vira `true` — empurrão único (não
  repete todo ciclo enquanto continuar atrasada), lembrando do prazo de
  bloqueio do fornecimento (vencimento + 7 dias corridos). Pode ser
  desativado na aba **Automáticos**; desligado, o poller marca os atrasos
  como vistos sem avisar (ao religar, só os novos avisam).
- **Horário de envio** (aba **Automáticos**, padrão 08:00 às 20:00): atraso
  e lembrete de vencimento só saem nesse horário; fora dele esperam o
  primeiro ciclo dentro. Pagamento e chamado saem na hora. Configuração em
  `config.json` (chave `lembretes`), lida a cada ciclo — ver `lembretes.py`.
- **Lembrete de vencimento**: `invoice_date_due` está a N dias e a fatura
  ainda não foi paga — empurrão único. N se escolhe no painel, aba
  **Automáticos** (véspera, 2 a 7 dias ou desativado; padrão véspera). A
  véspera usa o tipo `boleto_vence_amanha` (todas as versões do app);
  2 a 7 dias usam `boleto_vence_em` (app 2.5.3+, as anteriores ignoram). Substitui por completo o antigo
  `VencimentoWorker` (WorkManager no app, removido) — mesma ação
  "Copiar código Pix" preservada (`invoice_qrcode` vai no payload como
  `pix_code`).

Faturas com `invoice_deleted=true` (excluída/substituída) são ignoradas
nos três eventos de fatura, senão notificaria sobre cobrança que não
vale mais. **`invoice_valid=false` NÃO entra nesse filtro** — parecia
correlacionar com cliente inativo/cancelado numa amostra pequena, mas o
usuário confirmou o significado real: pagamento feito manualmente no
escritório, fora da plataforma bancária (não indica nada sobre o
cliente). Chegou a bloquear por engano uma notificação de pagamento
real feito assim — corrigido.

### Como identifica a conta

O app assina, no login, o tópico FCM `conta_<hash>` — hash SHA-256 (16
primeiros caracteres hex) do CPF só com dígitos (ver `topico_conta_cpf()`
em `poller.py` e o equivalente em `SessionManager.kt` no app Android).
Nunca é o CPF cru — evita expor PII no nome do tópico.

### Configuração

**Instalação nova, do zero, num servidor**: o `./install.sh` (seção 2)
já pergunta interativamente se você quer configurar o poller e faz tudo
sozinho — URL/usuário/senha do Controllr, primeira execução (baseline)
e instalação do timer, só se a baseline funcionar. Não precisa dos
passos manuais abaixo nesse caso.

**Instalação já existente** (painel já rodando, poller sendo adicionado
depois, ou reconfiguração manual): siga os passos abaixo.

**Sempre rode `poller.py` pelo Python do virtualenv, nunca o `python`/
`python3` do sistema**: `/opt/aviso-broadcaster/venv/bin/python
poller.py` (mesmo binário que `controllr-poller.service` usa). `python3`
do sistema não tem `requests`/`firebase-admin` instalados (só o venv
tem, via `pip install -r requirements.txt`); em muitos Debian, `python`
sem mais nada aponta pro Python 2, que nem entende o arquivo (erro de
"Non-ASCII character... but no encoding declared").

1. No Controllr, crie um usuário admin **dedicado, só leitura** pra essa
   função (não reaproveite login pessoal).
2. Rode `/opt/aviso-broadcaster/venv/bin/python poller.py` uma vez
   manualmente — ele cria `controllr_config.json` com um template e
   para, avisando o que falta preencher (`base_url` da área
   **administrativa**, porta 8080/8081/8443 conforme configurado no
   Controllr — não é a mesma porta 443 que o app Android usa; `usuario`;
   `senha`). Validado em produção: `https://controllr.hotnet.net.br:8443/`
   — atenção ao `.net.br`, sem ele o domínio não resolve.
3. Preencha o arquivo e rode `/opt/aviso-broadcaster/venv/bin/python
   poller.py` **manualmente** de novo — essa primeira execução real só
   grava a baseline (nenhuma notificação é enviada nela, mesmo que
   existam milhares de faturas já pagas na janela — ver comentário em
   `poller.py`). Confirme pela aba
   Logs (`poller_ciclo`, "baseline gravada") antes de seguir.
4. Só depois da baseline gravada, instale como serviço + timer do
   systemd:

```bash
cp controllr-poller.service controllr-poller.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now controllr-poller.timer
```

5. Acompanhe pela aba **Histórico** do painel (eventos `poller_ciclo` e
   `poller_falha`) — reaproveita o mesmo `access_log.py` dos outros
   eventos.

Pra mudar o intervalo (padrão 1 hora): edite `OnUnitActiveSec` em
`controllr-poller.timer`, depois `systemctl daemon-reload && systemctl restart controllr-poller.timer`.

`controllr_config.json` e `poller_state.json` seguem o mesmo padrão de
`config.json`/`service-account.json`: nunca versionados no git,
permissão `600`.

**Status**: os 4 eventos (pagamento confirmado, chamado atualizado,
fatura atrasada, boleto vence amanhã) rodando em produção. O 4º
substituiu por completo o antigo lembrete local do app (`VencimentoWorker`,
removido) — não é mais um recurso separado, é o mesmo poller.

**Importante ao adicionar uma categoria nova**: a checagem de "primeira
execução" em `main()` (`poller.py`) é por categoria (`"faturas"`,
`"faturas_atrasadas"`, `"faturas_vence_amanha"`, `"chamados"` — `not in
estado`), não pelo arquivo inteiro — uma categoria nova populando o
mesmo `poller_state.json` que outra já usa precisa da própria checagem,
senão repete o bug já corrigido aqui duas vezes: tudo que já está
"ativo" na janela pareceria novo e notificaria em massa na primeira vez
que aquela categoria rodar.

## 10. Instalação nova num servidor diferente — `install.sh` resolve tudo

Pra reinstalar do zero (servidor novo, ex: trocar de provedor/VPS):
copie a pasta inteira do repo (com `service-account.json` já dentro, se
tiver) e rode `./install.sh` como root — ele cobre painel **e** poller
numa passada só (ver seção 2). Não precisa de nenhum passo manual desta
seção nem da seção 9 nesse caso; o script já pergunta tudo
interativamente e só ativa o timer do poller se a primeira execução
(baseline) funcionar.

**Isso só vale pra instalação nova.** Rodar `install.sh` de novo por
cima de uma instalação já existente não é suportado (ele não tem lógica
de "atualizar" — recriaria o usuário admin do painel do zero). Pra
atualizar uma instalação existente com as mudanças mais recentes de
código (painel + poller), sem afetar configuração/dados já salvos, siga
a seção 6 (atualização do painel) e, se o poller ainda não estiver
instalado nela, os passos manuais da seção 9.

**Atenção ao copiar a pasta inteira** (de um clone git limpo, não de
outra instalação/máquina de teste): não devem ir junto `config.json`,
`controllr_config.json`, `poller_state.json` nem `acessos.log` — são
estado de uma instância específica, `install.sh` cria os que precisar
do zero. Um clone git novo (`git clone` direto do repo) nunca tem esses
arquivos, então copiar a partir dele é sempre seguro.

## 11. Como desativar o piloto de push por conta (registro de reversão)

**Atualizado 2026-09-05 — leia isto antes de desativar**: diferente de
quando essa seção foi escrita pela primeira vez, o poller **já está em
produção** e o 4º evento (boleto vence amanhã) **substituiu** o antigo
`VencimentoWorker` local — esse Worker foi removido do app, não existe
mais como alternativa. Ou seja, desativar o poller agora significa
também perder o lembrete de "vence amanhã" por completo, não só voltar
pro estado local — não tem mais fallback automático nesse aviso
específico.

- **Parar tudo rápido**: `systemctl disable --now
  controllr-poller.timer` no servidor — para os 4 eventos na hora, sem
  tocar em mais nada. O painel web (`avisos_gerais`, Modelos) continua
  funcionando normalmente, sem nenhuma dependência do poller. Pra
  limpar de vez: remover `/etc/systemd/system/controllr-poller.timer`/
  `.service`, `controllr_config.json` e `poller_state.json` do
  servidor.
- **Reversão parcial** (só o boleto vence amanhã, mantendo os outros 3
  eventos): reverter só o commit que fez essa migração (app:
  `0e958ed`; painel: o commit que adicionou `processar_vence_amanha()`
  em `poller.py`) — isso restaura o `VencimentoWorker` local, mas exige
  reinstalar a build antiga do app em todo mundo, não é uma operação
  "só servidor".
- **Reversão completa do código** (tira o piloto inteiro do histórico):
  `git revert` dos commits `511dff1`, `aafc78b`, `9f3fc35`, `d17298b`,
  `7efc461`, `8da1662`, `c40f361` neste repo, e
  `a076e19`/`cd90797`/`45bd4e4`/`e182c9f`/`0e958ed` no repo do app
  Android — nessa ordem inclui a remoção do `VencimentoWorker`, então
  reverter tudo restaura o comportamento local original.
