# TG Forecast

Bot em Python que envia para o Telegram a previsao do tempo e avisos meteorologicos do IPMA para uma area configuravel. Inclui stickers/imagens correspondentes aos codigos de tempo e foi pensado para execucao automatizada.

## Funcionalidades

- Consulta previsao diaria do IPMA e envia resumo para o Telegram.
- Monitoriza avisos meteorologicos e evita notificacoes duplicadas.
- Escolhe automaticamente sticker (.tgs) ou imagem (.png) conforme disponibilidade em `images/`.
- Configuracao por variaveis de ambiente para integrar em pipelines e cloud runners.

## Requisitos

- Python >= 3.10
- Conta de bot no Telegram e respetivo token (`BOT_TOKEN`).
- Acesso aos endpoints publicos do IPMA.

## Configuracao

1) Crie um ficheiro `.env` (nao o commit) com as variaveis:

    ```ini
    BOT_TOKEN=seu_bot_token
    CHAT_ID=id_do_chat_destino
    IPMA_WARNINGS_URL=https://api.ipma.pt/open-data/forecast/warnings/warnings_www.json
    IPMA_FORECAST_BASE=https://api.ipma.pt/open-data/forecast/meteorology/cities/daily/
    IPMA_GLOBAL_ID=1010500              # globalIdLocal do IPMA
    TARGET_AREA_ID=AVEIRO               # idAreaAviso do IPMA
    DISTRICTS_URL=https://api.ipma.pt/open-data/forecast/warnings/warnings_districts.json
    WEATHER_TYPES_URL=https://api.ipma.pt/open-data/weather-type-classe.json
    WIND_TYPES_URL=https://api.ipma.pt/open-data/wind-speed-daily-class.json
    CHECK_INTERVAL_MINUTES=60           # minutos entre checks de avisos
    FORECAST_TIME=20:30                 # hora local para previsao diaria
    ```

2) Verifique se a pasta `images/` esta presente (necessaria para stickers/imagens).

## Execucao local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python forecast.py
```

O script usa `schedule` para correr continuamente: mantenha o processo ativo (ex.: `nohup`, servico, ou sessao tmux/screen).

## Docker

Construcao e execucao simples:

```bash
docker build -t tg-forecast .
docker run --env-file .env tg-forecast
```

Com docker-compose:

```bash
docker compose up --build
```

## Estrutura

- `forecast.py`: logica principal (fetch IPMA, formatacao, envio Telegram).
- `images/`: stickers e imagens mapeadas para `idWeatherType` e avisos IPMA.
- `requirements.txt`: dependencias Python.

## Contribuir

1. Crie uma branch a partir de `main`.
2. Adicione testes/checks relevantes.
3. Abra um PR com descricao curta do problema/solucao e validacoes executadas.

## Suporte

Abra um issue no GitHub com detalhes e passos para reproduzir.
