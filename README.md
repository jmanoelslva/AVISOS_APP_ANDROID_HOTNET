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
   sem essa lista, qualquer IP consegue acessar a tela de login.
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
fortemente colocar um **Nginx com Let's Encrypt (certbot)** como proxy
reverso na frente dessa porta, especialmente se o servidor for acessível
pela internet (e não só pela sua rede interna/VPN).

## 5. Enviar um aviso

Depois de logado, a tela inicial já é o formulário de envio: título
(opcional) + mensagem, com opção de escolher um **modelo pronto**
(gerenciado na aba "Modelos") em vez de escrever do zero toda vez. Ao
enviar, todo cliente com o app instalado e conectado à internet recebe
a notificação em poucos segundos.

A aba **"Logs"** mostra o histórico de login (sucesso/falha), avisos
enviados e alterações de usuário — os últimos 500 eventos, guardados
localmente em `acessos.log` (não versionado no git).

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
