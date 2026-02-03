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
DISTRICTS_URL = os.getenv("DISTRICTS_URL")
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

# --- MAPEAMENTO IPMA -> FICHEIROS ---
# Mapeia o ID do IPMA para o NOME BASE do ficheiro (sem 0 ou 1)
IPMA_TO_FILENAME = {
    0: "UNKNOWN",   # Sem info
    1: "CLEAR",     # Céu limpo
    2: "PCLOUDY",   # Pouco nublado
    3: "PCLOUDY",   # Dispersamente nublado
    4: "MCLOUDY",   # Muito nublado
    5: "MCLOUDY",   # Nuvens altas
    6: "SHOWER",    # Aguaceiros/chuva
    7: "SHOWER",    # Aguaceiros fracos
    8: "SHOWER",    # Aguaceiros fortes
    9: "RAIN",      # Chuva/aguaceiros
    10: "RAIN",     # Chuva fraca
    11: "RAIN",     # Chuva forte
    12: "RAIN",     # Períodos chuva
    13: "RAIN",     # Períodos chuva fraca
    14: "RAIN",     # Períodos chuva forte
    15: "RAIN",     # Chuvisco
    16: "FOG",      # Neblina
    17: "FOG",      # Nevoeiro
    18: "SNOW",     # Neve
    19: "TSTORM",   # Trovoada
    20: "TSHOWER",  # Aguaceiros e Trovoada
    21: "HAIL",     # Granizo
    22: "LSNOW",    # Geada (Usei LSNOW como aproximação visual)
    23: "TSTORM",   # Chuva e Trovoada
    24: "MCLOUDY",  # Nebulosidade convectiva
    25: "MCLOUDY",  # Céu com períodos de muito nublado
    26: "FOG",      # Nevoeiro
    27: "MCLOUDY",  # Céu nublado
    28: "LSNOW",    # Aguaceiros de neve
    29: "SLEET",    # Chuva e Neve
    30: "SLEET"     # Chuva e Neve
}

# Dicionário Weather Types
WEATHER_TYPES = {
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

# --- Funções Auxiliares ---

def get_location_name():
    global location_name_cache
    if location_name_cache: return location_name_cache
    try:
        if not DISTRICTS_URL: return AREA_ID
        data = requests.get(DISTRICTS_URL, timeout=10).json()
        for item in data['data']:
            if item['idAreaAviso'] == AREA_ID:
                location_name_cache = item['local']
                return location_name_cache
        location_name_cache = AREA_ID
        return AREA_ID
    except:
        return AREA_ID

def get_weather_desc(type_id):
    return WEATHER_TYPES.get(int(type_id), f"Desconhecido ({type_id})")

def get_local_image_path(weather_id):
    """
    Constrói o caminho da imagem:
    1. Obtém nome base (ex: CLEAR)
    2. Verifica hora (0=Noite, 1=Dia)
    3. Retorna 'images/CLEAR1.png'
    """
    hour = datetime.now().hour
    # Lógica simples: Dia entre 07h e 20h
    suffix = "1" if 7 <= hour <= 20 else "0"

    # Obtém o nome base (Fallback para UNKNOWN se o ID não existir)
    base_name = IPMA_TO_FILENAME.get(int(weather_id), "UNKNOWN")

    # Nome do ficheiro: NOME + SUFIXO + .png
    filename = f"{base_name}{suffix}.png"
    filepath = os.path.join(IMAGES_DIR, filename)

    if os.path.exists(filepath):
        return filepath
    else:
        # Fallback: Tenta sem sufixo (ex: CLEAR.png) se a versão dia/noite falhar
        fallback_path = os.path.join(IMAGES_DIR, f"{base_name}.png")
        if os.path.exists(fallback_path):
            return fallback_path

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

        logging.info(f"Foto enviada: {image_path}")

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

        location_name = get_location_name()

        # Gera o caminho local da imagem
        image_path = get_local_image_path(forecast['idWeatherType'])

        caption = (
            f"📅 *Meteo: {forecast['forecastDate']}*\n"
            f"📍 {location_name}\n"
            f"🌤️ {get_weather_desc(forecast['idWeatherType'])}\n"
            f"🌡️ Min: {forecast['tMin']}ºC | Max: {forecast['tMax']}ºC\n"
            f"☔ Chuva: {forecast['precipitaProb']}%\n"
            f"💨 Vento: {forecast['classWindSpeed']} (Rumo: {forecast['predWindDir']})"
        )

        if image_path:
            send_telegram_photo_local(caption, image_path)
        else:
            send_message_text(caption)

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
                msg = (
                    f"⚠️ *AVISO IPMA: {location_name}*\n"
                    f"Tipo: {w['awarenessTypeName']}\n"
                    f"🔴 Nível: {w['awarenessLevelID'].upper()}\n"
                    f"🕒 {w['startTime']} até {w['endTime']}\n"
                    f"📝 {w['text']}"
                )
                send_message_text(msg)
                sent_warnings_cache.add(w_id)
    except Exception as e:
        logging.error(f"Erro avisos: {e}")

# --- Main ---

if __name__ == "__main__":
    logging.info("Bot Iniciado.")

    if not os.path.exists(IMAGES_DIR):
        logging.error(f"❌ Erro: Pasta '{IMAGES_DIR}' não encontrada.")
        exit()

    get_location_name()
    #job_forecast() # Teste

    schedule.every(CHECK_INTERVAL).minutes.do(job_warnings)
    schedule.every().day.at(FORECAST_TIME).do(job_forecast)

    while True:
        schedule.run_pending()
        time.sleep(1)