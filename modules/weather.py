import os
import time
import logging
import html
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests
import schedule
from dotenv import load_dotenv
from modules.db import get_db
from modules.telegram_bot import send_telegram_media, send_message_text

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
GLOBAL_ID = os.getenv("IPMA_GLOBAL_ID")
AREA_ID = os.getenv("TARGET_AREA_ID") or ""
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_MINUTES", 60))
FORECAST_TIME = os.getenv("FORECAST_TIME", "20:30")

IMAGES_DIR = "images"
WARNINGS_CACHE_RETENTION_HOURS = 168
WARNING_EXPIRY_GRACE_HOURS = 6

location_name_cache: str = ""
weather_types_cache: Optional[Dict[int, str]] = None
wind_types_cache: Optional[Dict[int, str]] = None

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

WIND_DIR_PT = {
    "N": "Norte", "NE": "Nordeste", "E": "Este", "SE": "Sudeste",
    "S": "Sul", "SW": "Sudoeste", "W": "Oeste", "NW": "Noroeste",
}

WARNING_STICKERS = {
    "Agitação Marítima": "coastalevent",
    "Nevoeiro": "fog",
    "Tempo Quente": "high-temperature",
    "Tempo Frio": "low-temperature",
    "Precipitação": "rain",
    "Neve": "snow-ice",
    "Trovoada": "thunderstorm",
    "Vento": "wind",
}

def cleanup_sent_warnings_cache() -> int:
    """Remove entradas expiradas do cache de avisos na SQLite."""
    now_ts = time.time()
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM ipma_warnings WHERE expiry_ts <= ?", (now_ts,))
    removed = c.rowcount
    conn.commit()
    conn.close()
    return removed

def get_warning_expiry_ts(end_time_raw: str) -> float:
    now_ts = time.time()
    fallback_expiry = now_ts + WARNINGS_CACHE_RETENTION_HOURS * 3600
    try:
        end_time = datetime.strptime(end_time_raw, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return fallback_expiry

    end_with_grace = end_time + timedelta(hours=WARNING_EXPIRY_GRACE_HOURS)
    expiry_ts = end_with_grace.timestamp()

    if expiry_ts <= now_ts:
        grace_hours = max(WARNING_EXPIRY_GRACE_HOURS, 1)
        return now_ts + grace_hours * 3600
    return expiry_ts


def get_location_name() -> str:
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
        mapping = {
            int(item["idWeatherType"]): item.get(
                "descWeatherTypePT",
                f"Desconhecido ({item['idWeatherType']})"
            )
            for item in data
        }
        weather_types_cache = mapping if mapping else WEATHER_TYPES_FALLBACK
    except Exception as e:
        logging.error(f"Erro ao carregar weather types: {e}")
        weather_types_cache = WEATHER_TYPES_FALLBACK

    return weather_types_cache


def load_wind_types() -> Dict[int, str]:
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
            int(item.get("classWindSpeed")): item.get(
                "descClassWindSpeedDailyPT",
                item.get("descClassWindSpeedPT"),
                str(item.get("classWindSpeed"))
            )
            for item in data
            if item.get("classWindSpeed") is not None
        }
    except Exception as e:
        logging.error(f"Erro ao carregar wind types: {e}")
        wind_types_cache = {}

    return wind_types_cache


def resolve_wind_desc(raw_code: Any) -> str:
    wind_map = load_wind_types()
    try:
        code_int = int(str(raw_code).strip())
        return wind_map.get(code_int, str(raw_code))
    except Exception:
        return str(raw_code)


def get_wind_dir_desc(dir_code: str) -> str:
    return WIND_DIR_PT.get(dir_code, dir_code)


def get_local_image_path(weather_id: int) -> Optional[str]:
    wid = int(weather_id)
    if wid < 10:
        base = f"w_ic_d_0{wid}"
    else:
        base = f"w_ic_d_{wid}"

    tgs_path = os.path.join(IMAGES_DIR, base + ".tgs")
    if os.path.exists(tgs_path):
        return tgs_path

    png_path = os.path.join(IMAGES_DIR, base + ".png")
    if os.path.exists(png_path):
        return png_path

    return None


def get_warning_sticker_path(awareness_type: str) -> Optional[str]:
    base_filename = WARNING_STICKERS.get(awareness_type)
    if not base_filename:
        return None

    tgs_path = os.path.join(IMAGES_DIR, base_filename + ".tgs")
    if os.path.exists(tgs_path):
        return tgs_path

    png_path = os.path.join(IMAGES_DIR, base_filename + ".png")
    if os.path.exists(png_path):
        return png_path

    return None

# --- Jobs ---

def job_forecast() -> None:
    logging.info("A processar previsão diária...")
    try:
        resp = requests.get(f"{FORECAST_BASE}{GLOBAL_ID}.json", timeout=15)
        resp.raise_for_status()
        forecast_data = resp.json().get('data', [])
        if len(forecast_data) > 1:
            forecast = forecast_data[1]
        elif len(forecast_data) == 1:
            logging.warning("Previsão para amanhã indisponível. A usar a previsão de hoje.")
            forecast = forecast_data[0]
        else:
            logging.warning("Sem dados de previsão disponíveis na resposta da API.")
            return

        weather_map = load_weather_types()
        id_weather = forecast.get('idWeatherType', -99)
        weather_desc = weather_map.get(
            int(id_weather),
            str(id_weather)
        )

        wind_code = forecast.get('classWindSpeed', -99)
        wind_desc = resolve_wind_desc(wind_code)

        location_name = get_location_name()

        try:
            pretty_date = datetime.strptime(
                forecast.get('forecastDate', ''),
                "%Y-%m-%d"
            ).strftime("%d-%m-%Y")
        except Exception:
            pretty_date = forecast.get('forecastDate', 'N/D')

        image_path = get_local_image_path(forecast.get('idWeatherType', 0))

        caption = (
            f"👀 <b>Previsão do tempo para amanhã:</b>\n"
            f"📅 <b>{html.escape(str(pretty_date))}</b>\n"
            f"\n"
            f"📍 Região: <b>{html.escape(str(location_name))}</b>\n"
            f"🌤️ {html.escape(str(weather_desc))}\n"
            f"🌡️ Min: {html.escape(str(forecast.get('tMin', 'N/D')))}ºC | Max: {html.escape(str(forecast.get('tMax', 'N/D')))}ºC\n"
            f"☔ Previsão de chuva: {html.escape(str(forecast.get('precipitaProb', 'N/D')))}%\n"
            f"💨 Vento de {html.escape(str(get_wind_dir_desc(forecast.get('predWindDir', 'N/D'))))} - "
            f"{html.escape(str(wind_desc))}\n"
            f"\n"
            f"🌍 Fonte: <a href=\"https://www.ipma.pt/pt/otempo/"
            f"prev.localidade.hora/#{html.escape(str(location_name), quote=True)}&{html.escape(str(location_name), quote=True)}\">ipma.pt</a>"
        )

        if image_path:
            send_telegram_media(caption, image_path)
            logging.info(f"Previsão enviada com imagem: {image_path}")
        else:
            send_message_text(caption)
            logging.info("Previsão enviada sem imagem.")

    except Exception as e:
        logging.error(f"Erro no job forecast: {e}")


def job_warnings() -> None:
    logging.info("A verificar avisos...")
    try:
        removed = cleanup_sent_warnings_cache()
        if removed:
            logging.info(f"Limpeza de cache: removidas {removed} entradas expiradas.")

        if not WARNINGS_URL:
            return
        resp = requests.get(WARNINGS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        relevant = [
            w for w in data
            if w.get('idAreaAviso') == AREA_ID and w.get('awarenessLevelID', '').lower() != 'green'
        ]

        if not relevant:
            return

        location_name = get_location_name()
        
        conn = get_db()
        c = conn.cursor()
        
        for w in relevant:
            start_time = w.get('startTime', '')
            start_date = start_time.split('T')[0] if start_time else 'N/D'
            w_id = (
                f"{w.get('idAreaAviso', 'N/D')}_{w.get('awarenessTypeName', 'N/D')}_"
                f"{w.get('awarenessLevelID', 'N/D')}_{start_date}"
            )
            
            c.execute("SELECT warning_id FROM ipma_warnings WHERE warning_id = ?", (w_id,))
            if not c.fetchone():
                try:
                    pretty_start = datetime.strptime(
                        start_time,
                        "%Y-%m-%dT%H:%M:%S"
                    ).strftime("%H:%M %d-%m-%Y")
                except Exception:
                    pretty_start = start_time.replace("T", " ") if start_time else 'N/D'

                end_time = w.get('endTime', '')
                try:
                    pretty_end = datetime.strptime(
                        end_time,
                        "%Y-%m-%dT%H:%M:%S"
                    ).strftime("%H:%M %d-%m-%Y")
                except Exception:
                    pretty_end = end_time.replace("T", " ") if end_time else 'N/D'

                try:
                    pretty_awareness = {
                        'YELLOW': '🟡 Alerta Amarelo',
                        'ORANGE': '🟠 Alerta Laranja',
                        'RED': '🔴 Alerta Vermelho',
                        'GREEN': '🟢 Alerta Verde'
                    }[w.get('awarenessLevelID', '').upper()]
                except KeyError:
                    pretty_awareness = str(w.get('awarenessLevelID', 'Desconhecido')).capitalize()

                msg = (
                    f"⚠️ <b>AVISO IPMA:</b>\n"
                    f"\n"
                    f"📍 Região: <b>{html.escape(str(location_name))}</b>\n"
                    f"🔔 {html.escape(str(w.get('awarenessTypeName', 'N/D')))}\n"
                    f"{html.escape(str(pretty_awareness))}\n"
                    f"🕒 {html.escape(str(pretty_start))} até {html.escape(str(pretty_end))}\n"
                    f"\n"
                    f"📝 {html.escape(str(w.get('text', 'N/D')))}\n"
                    f"\n"
                    f"🌍 Fonte: <a href=\"https://www.ipma.pt/pt/otempo/"
                    f"prev-sam/?p={html.escape(str(AREA_ID), quote=True)}\">ipma.pt</a>"
                )
                sticker_path = get_warning_sticker_path(w.get('awarenessTypeName', ''))
                if sticker_path:
                    send_telegram_media(msg, sticker_path)
                else:
                    send_message_text(msg)
                
                expiry = get_warning_expiry_ts(w.get('endTime', ''))
                c.execute("INSERT INTO ipma_warnings (warning_id, expiry_ts) VALUES (?, ?)", (w_id, expiry))
                conn.commit()
                logging.info(f"Aviso enviado: {w_id}")
            else:
                logging.info(f"Aviso já enviado: {w_id}")
                
        conn.close()
    except Exception as e:
        logging.error(f"Erro avisos: {e}")

if __name__ == "__main__":
    pass
