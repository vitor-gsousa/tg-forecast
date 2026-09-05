# TG Forecast & News

Este é um *bot* em Python que envia a previsão do tempo, avisos meteorológicos do IPMA e as suas notícias preferidas (através de Feeds RSS) diretamente para o Telegram. O projeto é totalmente modular e inclui uma interface Web (Dashboard) para gerir as suas subscrições e configurações de forma amigável.

## Funcionalidades

- **Meteorologia (IPMA)**: Consulta a previsão diária e monitoriza os avisos meteorológicos, suportando *stickers* (.tgs) e imagens (.png) estáticas para ilustrar a notificação.
- **Leitor de RSS**: Verifica os feeds que configurar na interface Web para nunca perder as novidades locais ou globais.
- **Filtro Anti-Spam e Duplicados**: Todo o histórico é guardado numa base de dados local (SQLite). O sistema utiliza inteligência algorítmica (`difflib`) para evitar o envio de notícias repetidas, comparando o título de artigos recentes de *todas* as fontes para evitar sobreposição (mesmo que a fonte seja diferente).
- **Interface Web**: Um *frontend* leve servido por Flask (na porta `8080`), permitindo-lhe adicionar/remover feeds, consultar os logs do sistema e editar as definições em tempo real sem ter de reabrir o código.

## Requisitos

- Python 3.10 ou superior.
- Uma conta de *bot* no Telegram e o respetivo *token* de acesso (`BOT_TOKEN`).
- Opcional: Docker e Docker Compose (para *deploy* robusto num servidor).

## Configuração

Crie um ficheiro chamado `.env` na raiz do projeto (basta copiar a estrutura de `.env.example`) com as variáveis base:

```ini
BOT_TOKEN=o_teu_token_do_telegram
CHAT_ID=o_id_do_chat_de_destino

# IPMA Configs
IPMA_WARNINGS_URL=https://api.ipma.pt/open-data/forecast/warnings/warnings_www.json
IPMA_FORECAST_BASE=https://api.ipma.pt/open-data/forecast/meteorology/cities/daily/
IPMA_GLOBAL_ID=1010500              # Identificador global do IPMA
TARGET_AREA_ID=AVEIRO               # Zona de aviso (ex: AVEIRO)
CHECK_INTERVAL_MINUTES=60           # Intervalo verificação meteorológica
FORECAST_TIME=20:30                 # Hora do relatório diário

# RSS & Web Configs
RSS_CHECK_INTERVAL_MINUTES=30       # A cada X minutos, vai ler as notícias novas
WEB_PORT=8080                       # Porta onde o painel web arranca
DB_PATH=data/tg_forecast.db         # Caminho para gravar a Base de Dados
```

> **Nota:** As opções principais (Intervalo do RSS, BOT_TOKEN e CHAT_ID) podem também ser configuradas ou editadas comodamente mais tarde no próprio **Dashboard Web**.

## Execução Local (Sem Docker)

```bash
python -m venv .venv

# Em Windows:
.venv\Scripts\activate
# Em Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

Ao correr, abra o browser em `http://localhost:8080` para adicionar os seus primeiros Feeds RSS.

## Deploy com Docker Compose

A forma recomendada de colocar a correr em produção. O projeto conta com um `docker-compose.yaml` pré-preparado que isola a base de dados num *volume* persistente para nunca perder as configurações:

```bash
docker compose up -d --build
```
Os seus dados (Logs, estado dos feeds e base de dados SQLite) serão permanentemente mantidos e geridos na pasta local `data/`.

## Estrutura do Projeto

- `main.py`: O orquestrador central que junta o agendador e o servidor Web em simultâneo.
- `modules/`: 
  - `db.py`: Lógica da base de dados e armazenamento do histórico em SQLite.
  - `weather.py`: Tratamento da API do IPMA (Avisos e Previsões).
  - `rss.py`: Lógica de *parsing* e validação de similaridade para artigos de notícias.
  - `telegram_bot.py`: Módulo utilitário para expedir os alertas visuais e textuais.
- `web/`:
  - `app.py`: A lógica do *Backend* Flask que serve os ecrãs de gestão.
  - `templates/`: Ficheiros HTML do design da interface.
- `images/`: Local para guardar os *stickers* associados à meteorologia.
