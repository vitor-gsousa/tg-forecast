import os
import time
import requests
import schedule
import logging
from datetime import datetime
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
WIND_TYPES = os.getenv("WIND_TYPES_URL") or os.getenv("WIND_TYPES")
CITY_ID = os.getenv("IPMA_CITY_ID")
AREA_ID = os.getenv("TARGET_AREA_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_MINUTES", 60))
FORECAST_TIME = os.getenv("FORECAST_TIME", "08:00")
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")

IMAGES_DIR = "images"

# Caches
sent_warnings_cache = set()
location_name_cache = None
weather_types_cache = None
wind_types_cache = None

# Dicionário Weather Types
# Fallback local caso o endpoint de tipos não responda
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
    29: "Chuva e Neve", 30: "Chuva e Neve"
}

# Conversão de rumo do vento para PT
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

# --- Funções Auxiliares ---

def get_location_name():
    global location_name_cache
    if location_name_cache: return location_name_cache
    try:
        if not DISTRICTS: return AREA_ID
        data = requests.get(DISTRICTS, timeout=10).json()
        for item in data['data']:
            if item['idAreaAviso'] == AREA_ID:
                location_name_cache = item['local']
                return location_name_cache
        location_name_cache = AREA_ID
        return AREA_ID
    except:
        return AREA_ID

def load_weather_types():
    """Carrega os tipos de tempo da API (descWeatherTypePT), com cache e fallback local."""
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
        # Se por algum motivo ficar vazio, usa fallback
        weather_types_cache = mapping if mapping else WEATHER_TYPES_FALLBACK
    except Exception as e:
        logging.error(f"Erro ao carregar weather types: {e}")
        weather_types_cache = WEATHER_TYPES_FALLBACK

    return weather_types_cache

def load_wind_types():
    """Carrega classes de vento da API (descClassWindSpeedDailyPT), com cache e fallback no próprio código."""
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

def resolve_wind_desc(raw_code):
    """Normaliza o código de vento (string/int) e devolve descrição PT se existir."""
    wind_map = load_wind_types()
    try:
        code_int = int(str(raw_code).strip())
        return wind_map.get(code_int, str(raw_code))
    except Exception:
        return str(raw_code)

def get_wind_dir_desc(dir_code):
    return WIND_DIR_PT.get(dir_code, dir_code)

def get_local_image_path(weather_id):
    """
    Constrói o caminho da imagem dia usando o padrão w_ic_d_<id>.png
    - Se id < 10: w_ic_d_0{id}.png
    - Caso contrário: w_ic_d_{id}.png
    """
    wid = int(weather_id)
    if wid < 10:
        filename = f"w_ic_d_0{wid}.png"
    else:
        filename = f"w_ic_d_{wid}.png"

    filepath = os.path.join(IMAGES_DIR, filename)

    if os.path.exists(filepath):
        return filepath
    else:
        # Fallback: Tenta sem sufixo (ex: CLEAR.png) se a versão dia/noite falhar
        #fallback_path = os.path.join(IMAGES_DIR, f"{base_name}.png")
        #if os.path.exists(fallback_path):
        #    return fallback_path

        logging.warning(f"Imagem não encontrada: {filepath}")
        return None

def send_telegram_photo_local(caption, image_path):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "Markdown",
        }

        # Abre o ficheiro binário e envia
        with open(image_path, 'rb') as f:
            files = {"photo": f}
            resp = requests.post(url, data=data, files=files, timeout=30)
            resp.raise_for_status()

        #logging.info(f"Foto enviada: {image_path}")

    except Exception as e:
        logging.error(f"Erro ao enviar foto: {e}")
        # Fallback:
        send_message_text(caption)

def send_message_text(msg):
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

def job_forecast():
    logging.info(f"A processar previsão diária...")
    try:
        resp = requests.get(f"{FORECAST_BASE}{CITY_ID}.json", timeout=15)
        resp.raise_for_status()
        forecast = resp.json()['data'][0]

        weather_map = load_weather_types()
        weather_desc = weather_map.get(int(forecast['idWeatherType']), str({forecast['idWeatherType']}))
        wind_map = load_wind_types()
        wind_desc = wind_map.get(int(forecast['classWindSpeed']), str(forecast['classWindSpeed']))

        location_name = get_location_name()

        try:
            pretty_date = datetime.strptime(forecast['forecastDate'], "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            pretty_date = forecast['forecastDate']

        # Gera o caminho local da imagem
        image_path = get_local_image_path(forecast['idWeatherType'])

        caption = (
            f"📅 *Meteo: {pretty_date}*\n"
            f"📍 {location_name}\n"
            f"🌤️ {weather_desc}\n"
            f"🌡️ Min: {forecast['tMin']}ºC | Max: {forecast['tMax']}ºC\n"
            f"☔ Previsão de chuva: {forecast['precipitaProb']}%\n"
            f"💨 Vento: {wind_desc} (Rumo: {get_wind_dir_desc(forecast['predWindDir'])})"
        )

        if image_path:
            send_telegram_photo_local(caption, image_path)
            logging.info(f"Previsão enviada com imagem.")
        else:
            send_message_text(caption)
            logging.info(f"Previsão enviada sem imagem.")

    except Exception as e:
        logging.error(f"Erro no job forecast: {e}")

def job_warnings():
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

                msg = (
                    f"⚠️ *AVISO IPMA: {location_name}*\n"
                    f"Tipo: {w['awarenessTypeName']}\n"
                    f"🔴 Nível: {w['awarenessLevelID'].upper()}\n"
                    f"🕒 {pretty_start} até {pretty_end}\n"
                    f"📝 {w['text']}"
                )
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
    logging.info("Testes executados.")
    #job_warnings() # Teste

    schedule.every(CHECK_INTERVAL).minutes.do(job_warnings)
    schedule.every().day.at(FORECAST_TIME).do(job_forecast)

    while True:
        schedule.run_pending()
        time.sleep(1)