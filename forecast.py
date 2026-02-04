import os
import time
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import requests
import schedule
from dotenv import load_dotenv

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()

# --- Configurações ---
WARNINGS_URL = os.getenv("IPMA_WARNINGS_URL")
FORECAST_BASE = os.getenv("IPMA_FORECAST_BASE")
DISTRICTS = os.getenv("DISTRICTS_URL")
WEATHER_TYPES = os.getenv("WEATHER_TYPES_URL")
WIND_TYPES = os.getenv("WIND_TYPES_URL")
CITY_ID = os.getenv("IPMA_CITY_ID")
AREA_ID = os.getenv("TARGET_AREA_ID") or ""
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_MINUTES", 60))
FORECAST_TIME = os.getenv("FORECAST_TIME", "20:30")
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")

IMAGES_DIR = "images"

# Caches em memória para reduzir chamadas externas repetidas
sent_warnings_cache: set[str] = set()
location_name_cache: str = ""
weather_types_cache: Optional[Dict[int, str]] = None
wind_types_cache: Optional[Dict[int, str]] = None

# Tipos de tempo: fallback local caso o endpoint falhe
WEATHER_TYPES_FALLBACK = {
    0: "Sem informação", 1: "Céu limpo", 2: "Céu pouco nublado",
    3: "Céu parcialmente nublado", 4: "Céu muito nublado ou encoberto",
    5: "Céu nublado por nuvens altas", 6: "Aguaceiros/chuva",
    7: "Aguaceiros/chuva fracos", 8: "Aguaceiros/chuva fortes",
    9: "Chuva/aguaceiros", 10: "Chuva fraca ou chuvisco",
    11: "Chuva/aguaceiros forte", 12: "Períodos de chuva",
    13: "Períodos de chuva fraca", 14: "Períodos de chuva forte",
    15: "Chuvisco", 16: "Neblina", 17: "Nevoeiro ou nuvens baixas",
    18: "Neve", 19: "Trovoada", 20: "Aguaceiros e possibilidade de trovoada",
    21: "Granizo", 22: "Geada", 23: "Chuva e possibilidade de trovoada",
    24: "Nebulosidade convectiva", 25: "Céu com períodos de muito nublado",
    26: "Nevoeiro", 27: "Céu nublado", 28: "Aguaceiros de neve",
    29: "Chuva e Neve", 30: "Chuva e Neve", -99: "---"
}

# Conversão de direção do vento para PT
WIND_DIR_PT = {
    "N": "Norte",
    "NE": "Nordeste",
    "E": "Este",
    "SE": "Sudeste",
    "S": "Sul",
    "SW": "Sudoeste",
    "W": "Oeste",
    "NW": "Noroeste",
}

# Mapeamento de avisos IPMA para stickers dedicados
WARNING_STICKERS = {
    "Agitação Marítima": "coastalevent.tgs",
    "Nevoeiro": "fog.tgs",
    "Tempo Quente": "high-temperature.tgs",
    "Tempo Frio": "low-temperature.tgs",
    "Precipitação": "rain.tgs",
    "Neve": "snow-ice.tgs",
    "Trovoada": "thunderstorm.tgs",
    "Vento": "wind.tgs",
}

# --- Funções Auxiliares ---

def get_location_name() -> str:
    """Resolve e cacheia o nome amigável da área alvo.

    Returns:
        str: Nome do distrito/área se resolvido; caso contrário devolve `AREA_ID`.
    """
    global location_name_cache
    if location_name_cache:
        return location_name_cache
    try:
        if not DISTRICTS:
            location_name_cache = AREA_ID
            return AREA_ID
        data = requests.get(DISTRICTS, timeout=10).json()
        for item in data['data']:
            if item['idAreaAviso'] == AREA_ID:
                location_name_cache = item['local']
                return location_name_cache
        location_name_cache = AREA_ID
        return AREA_ID
    except Exception:
        location_name_cache = AREA_ID
        return AREA_ID

def load_weather_types() -> Dict[int, str]:
    """Carrega tipos de tempo do IPMA com cache e fallback.

    Returns:
        Dict[int, str]: Mapa id→descrição PT de condições meteorológicas.
    """
    global weather_types_cache
    if weather_types_cache is not None:
        return weather_types_cache

    if not WEATHER_TYPES:
        weather_types_cache = WEATHER_TYPES_FALLBACK
        return weather_types_cache

    try:
        resp = requests.get(WEATHER_TYPES, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        mapping = {int(item["idWeatherType"]): item.get("descWeatherTypePT", f"Desconhecido ({item['idWeatherType']})") for item in data}
        weather_types_cache = mapping if mapping else WEATHER_TYPES_FALLBACK
    except Exception as e:
        logging.error(f"Erro ao carregar weather types: {e}")
        weather_types_cache = WEATHER_TYPES_FALLBACK

    return weather_types_cache

def load_wind_types() -> Dict[int, str]:
    """Carrega classes de vento do IPMA com cache e fallback interno.

    Returns:
        Dict[int, str]: Mapa classe de vento→descrição PT.
    """
    global wind_types_cache
    if wind_types_cache is not None:
        return wind_types_cache
    try:
        if not WIND_TYPES:
            wind_types_cache = {}
            return wind_types_cache

        resp = requests.get(WIND_TYPES, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        wind_types_cache = {
            int(item.get("classWindSpeed")): item.get("descClassWindSpeedDailyPT")
            or item.get("descClassWindSpeedPT")
            or str(item.get("classWindSpeed"))
            for item in data
            if item.get("classWindSpeed") is not None
        }
    except Exception as e:
        logging.error(f"Erro ao carregar wind types: {e}")
        wind_types_cache = {}

    return wind_types_cache

def resolve_wind_desc(raw_code: Any) -> str:
    """Normaliza código de vento e devolve descrição PT.

    Args:
        raw_code: Código recebido (string/int) do IPMA.

    Returns:
        str: Descrição PT se existir; caso contrário o próprio código.
    """
    wind_map = load_wind_types()
    try:
        code_int = int(str(raw_code).strip())
        return wind_map.get(code_int, str(raw_code))
    except Exception:
        return str(raw_code)

def get_wind_dir_desc(dir_code: str) -> str:
    """Expande abreviaturas de direção de vento para nomes completos.

    Args:
        dir_code: Abreviatura cardinal (ex.: ``NE``).

    Returns:
        str: Descrição por extenso ou o código original.
    """
    return WIND_DIR_PT.get(dir_code, dir_code)

def get_local_image_path(weather_id: int) -> Optional[str]:
    """Obtém caminho local da imagem correspondente ao ``weather_id``.

    Prioriza ficheiros ``.tgs`` e faz fallback para ``.png``.

    Args:
        weather_id: Identificador de condição meteorológica IPMA.

    Returns:
        Optional[str]: Caminho absoluto relativo à pasta de imagens ou ``None`` se não existir.
    """
    wid = int(weather_id)
    if wid < 10:
        base = f"w_ic_d_0{wid}"
    else:
        base = f"w_ic_d_{wid}"

    # Prefere sticker animado se existir .tgs
    tgs_path = os.path.join(IMAGES_DIR, base + ".tgs")
    if os.path.exists(tgs_path):
        return tgs_path

    # Caso não exista .tgs usa .png
    png_path = os.path.join(IMAGES_DIR, base + ".png")
    if os.path.exists(png_path):
        return png_path

    return None

def get_warning_sticker_path(awareness_type: str) -> Optional[str]:
    """Devolve o caminho do sticker associado ao tipo de aviso, se existir localmente."""
    filename = WARNING_STICKERS.get(awareness_type)
    if not filename:
        return None
    path = os.path.join(IMAGES_DIR, filename)
    return path if os.path.exists(path) else None

def send_telegram_media(caption: str, image_path: str) -> None:
    """Envia media para o Telegram, usando sticker para ``.tgs`` ou foto caso contrário."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return

    try:
        ext = os.path.splitext(image_path)[1].lower()

        # Escolhe endpoint conforme a extensão (.tgs → sticker, resto → foto)
        if ext == '.tgs':
            method = "sendSticker"
            file_key = "sticker"
            has_caption = False # Stickers não têm legenda
        else:
            method = "sendPhoto"
            file_key = "photo"
            has_caption = True

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
        data = {"chat_id": TELEGRAM_CHAT_ID}

        if has_caption:
            data["caption"] = caption
            data["parse_mode"] = "Markdown"

        with open(image_path, 'rb') as f:
            files = {file_key: f}
            resp = requests.post(url, data=data, files=files, timeout=30)
            resp.raise_for_status()

        if not has_caption:
            send_message_text(caption)

    except Exception as e:
        logging.error(f"Erro ao enviar media ({image_path}): {e}")
        send_message_text(caption)

def send_message_text(msg: str) -> None:
    """Envia uma mensagem de texto simples para o chat Telegram configurado."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        logging.error(f"Erro envio texto: {e}")

# --- Jobs ---

def job_forecast() -> None:
    """Obtém previsão diária do IPMA, formata e envia via Telegram (com imagem se existir)."""
    logging.info(f"A processar previsão diária...")
    try:
        resp = requests.get(f"{FORECAST_BASE}{CITY_ID}.json", timeout=15)
        resp.raise_for_status()
        forecast = resp.json()['data'][1]

        weather_map = load_weather_types()
        weather_desc = weather_map.get(int(forecast['idWeatherType']), str(forecast['idWeatherType']))

        wind_code = forecast['classWindSpeed']
        wind_desc = resolve_wind_desc(wind_code)

        location_name = get_location_name()

        try:
            pretty_date = datetime.strptime(forecast['forecastDate'], "%Y-%m-%d").strftime("%d-%m-%Y")
        except:
            pretty_date = forecast['forecastDate']

        image_path = get_local_image_path(forecast['idWeatherType'])

        caption = (
            f"👀 *Previsão do tempo para amanhã:*\n"
            f"📅 *{pretty_date}*\n"
            f"\n"
            f"📍 Região: *{location_name}*\n"
            f"🌤️ {weather_desc}\n"
            f"🌡️ Min: {forecast['tMin']}ºC | Max: {forecast['tMax']}ºC\n"
            f"☔ Previsão de chuva: {forecast['precipitaProb']}%\n"
            f"💨 Vento de {get_wind_dir_desc(forecast['predWindDir'])} - {wind_desc}\n"
            f"\n"
            f"🌍 Fonte: [ipma.pt](https://www.ipma.pt/pt/otempo/prev.localidade.hora/)"
        )

        if image_path:
            send_telegram_media(caption, image_path) # Usa helper que decide sticker/foto
            logging.info(f"Previsão enviada com imagem: {image_path}")
        else:
            send_message_text(caption)
            logging.info(f"Previsão enviada sem imagem.")

    except Exception as e:
        logging.error(f"Erro no job forecast: {e}")

def job_warnings() -> None:
    """Consulta avisos meteorológicos para a área alvo e envia novos alertas via Telegram."""
    logging.info(f"A verificar avisos...")
    try:
        if not WARNINGS_URL: return
        resp = requests.get(WARNINGS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        relevant = [w for w in data if w['idAreaAviso'] == AREA_ID and w['awarenessLevelID'] != 'green']

        if not relevant: return

        location_name = get_location_name()
        for w in relevant:
            w_id = f"{w['idAreaAviso']}_{w['awarenessTypeName']}_{w['startTime']}"
            if w_id not in sent_warnings_cache:
                try:
                    pretty_start = datetime.strptime(w['startTime'], "%Y-%m-%dT%H:%M:%S").strftime("%H:%M %d-%m-%Y")
                except Exception:
                    pretty_start = w['startTime'].replace("T", " ")

                try:
                    pretty_end = datetime.strptime(w['endTime'], "%Y-%m-%dT%H:%M:%S").strftime("%H:%M %d-%m-%Y")
                except Exception:
                    pretty_end = w['endTime'].replace("T", " ")

                try:
                    pretty_awareness = {
                        'YELLOW': '🟡 Alerta Amarelo',
                        'ORANGE': '🟠 Alerta Laranja',
                        'RED': '🔴 Alerta Vermelho',
                        'GREEN': '🟢 Alerta Verde'
                    }[w['awarenessLevelID'].upper()]
                except KeyError:
                    pretty_awareness = w['awarenessLevelID'].capitalize()

                msg = (
                    f"⚠️ *AVISO IPMA:*\n"
                    f"\n"
                    f"📍 Região: *{location_name}*\n"
                    f"🔔 {w['awarenessTypeName']}\n"
                    f"{pretty_awareness}\n"
                    f"🕒 {pretty_start} até {pretty_end}\n"
                    f"\n"
                    f"📝 {w['text']}\n"
                    f"\n"
                    f"🌍 Fonte: [ipma.pt](https://www.ipma.pt/pt/otempo/prev-sam/)"
                )
                sticker_path = get_warning_sticker_path(w['awarenessTypeName'])
                if sticker_path:
                    send_telegram_media(msg, sticker_path)
                else:
                    send_message_text(msg)
                sent_warnings_cache.add(w_id)
                logging.info(f"Aviso enviado: {w_id}")
            else:
                logging.info(f"Aviso já enviado: {w_id}")
    except Exception as e:
        logging.error(f"Erro avisos: {e}")

# --- Main ---

if __name__ == "__main__":
    logging.info("Bot Iniciado.")

    if not os.path.exists(IMAGES_DIR):
        logging.error(f"❌ Erro: Pasta '{IMAGES_DIR}' não encontrada.")
        exit()

    get_location_name()
    job_forecast() # Teste
    logging.info("Testes previsões meteo executados.")
    job_warnings() # Teste
    logging.info("Testes avisos executados.")

    schedule.every(CHECK_INTERVAL).minutes.do(job_warnings)
    schedule.every().day.at(FORECAST_TIME).do(job_forecast)

    while True:
        schedule.run_pending()
        time.sleep(1)