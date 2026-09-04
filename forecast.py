import os
import time
import logging
import json
import html
from datetime import datetime, timedelta
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
GLOBAL_ID = os.getenv("IPMA_GLOBAL_ID")
AREA_ID = os.getenv("TARGET_AREA_ID") or ""
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_MINUTES", 60))
FORECAST_TIME = os.getenv("FORECAST_TIME", "20:30")
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")

IMAGES_DIR = "images"
WARNINGS_CACHE_FILE = os.getenv(
    "WARNINGS_CACHE_FILE",
    "sent_warnings_cache.json"
)
WARNINGS_CACHE_RETENTION_HOURS = int(
    os.getenv("WARNINGS_CACHE_RETENTION_HOURS", 168)
)
WARNING_EXPIRY_GRACE_HOURS = int(os.getenv("WARNING_EXPIRY_GRACE_HOURS", 6))

# Cache em memória para reduzir chamadas externas repetidas.
# Formato: id aviso -> timestamp Unix de expiração.
sent_warnings_cache: dict[str, float] = {}
location_name_cache: str = ""
weather_types_cache: Optional[Dict[int, str]] = None
wind_types_cache: Optional[Dict[int, str]] = None

# Fallback local para tipos de tempo quando o endpoint falha.
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

# Conversão de direção do vento para PT.
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

# Mapeamento de avisos IPMA para stickers dedicados.
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


def ensure_warnings_cache_storage() -> bool:
    """Garante que o storage de cache local está pronto a usar.

    Returns:
        bool: ``True`` se a pasta/ficheiro de cache estiverem disponíveis;
            ``False`` em caso de falha.
    """
    if not WARNINGS_CACHE_FILE:
        return False

    try:
        cache_dir = os.path.dirname(WARNINGS_CACHE_FILE)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

        if not os.path.exists(WARNINGS_CACHE_FILE):
            with open(WARNINGS_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            logging.info(f"Ficheiro de cache criado: {WARNINGS_CACHE_FILE}")
        return True
    except Exception as e:
        logging.error(
            f"Erro ao preparar storage de cache ({WARNINGS_CACHE_FILE}): {e}"
        )
        return False


def load_sent_warnings_cache() -> None:
    """Carrega o cache de avisos enviados a partir do JSON local.

    Returns:
        None: Atualiza o estado global ``sent_warnings_cache``.
    """
    global sent_warnings_cache
    if not ensure_warnings_cache_storage():
        return

    try:
        with open(WARNINGS_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, dict):
            parsed_cache: dict[str, float] = {}
            for k, v in data.items():
                try:
                    parsed_cache[str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
            sent_warnings_cache = parsed_cache
            removed = cleanup_sent_warnings_cache()
            msg = (
                f"Cache de avisos carregado com {len(sent_warnings_cache)} "
                "entradas"
            )
            if removed:
                msg += f" ({removed} expiradas removidas)."
            else:
                msg += "."
            logging.info(msg)
        elif isinstance(data, list):
            # Mantém compatibilidade com formato legado sem expiração.
            expiry = time.time() + WARNINGS_CACHE_RETENTION_HOURS * 3600
            sent_warnings_cache = {str(item): expiry for item in data}
            logging.info(
                f"Cache legado carregado com {len(sent_warnings_cache)} "
                f"entradas; convertido para formato com expiração "
                f"({WARNINGS_CACHE_RETENTION_HOURS}h)."
            )
            save_sent_warnings_cache()
        else:
            logging.warning(
                f"Formato inválido em {WARNINGS_CACHE_FILE}. "
                f"A iniciar cache vazio."
            )
            sent_warnings_cache = {}
            save_sent_warnings_cache()
    except Exception as e:
        logging.error(
            f"Erro ao carregar cache de avisos ({WARNINGS_CACHE_FILE}): {e}"
        )
        sent_warnings_cache = {}
        save_sent_warnings_cache()


def cleanup_sent_warnings_cache() -> int:
    """Remove entradas expiradas do cache de avisos.

    Returns:
        int: Quantidade de entradas removidas.
    """
    global sent_warnings_cache
    now_ts = time.time()
    before = len(sent_warnings_cache)
    sent_warnings_cache = {
        k: v for k, v in sent_warnings_cache.items() if v > now_ts
    }
    return before - len(sent_warnings_cache)


def get_warning_expiry_ts(end_time_raw: str) -> float:
    """Calcula o timestamp de expiração de um aviso.

    Args:
        end_time_raw: Data/hora de fim do aviso no formato
            ``YYYY-MM-DDTHH:MM:SS``.

    Returns:
        float: Timestamp Unix da expiração (fim + período de graça), com
            fallback para uma expiração segura quando o formato é inválido.
    """
    now_ts = time.time()
    fallback_hours = max(WARNINGS_CACHE_RETENTION_HOURS, 1)
    fallback_expiry = now_ts + fallback_hours * 3600
    try:
        end_time = datetime.strptime(end_time_raw, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return fallback_expiry

    end_with_grace = end_time + timedelta(hours=WARNING_EXPIRY_GRACE_HOURS)
    expiry_ts = end_with_grace.timestamp()

    # Evita expiração imediata quando o fim do aviso já passou.
    if expiry_ts <= now_ts:
        grace_hours = max(WARNING_EXPIRY_GRACE_HOURS, 1)
        return now_ts + grace_hours * 3600
    return expiry_ts


def save_sent_warnings_cache() -> None:
    """Persiste o cache de avisos enviados em JSON local.

    Returns:
        None: Escreve o estado global ``sent_warnings_cache`` em disco.
    """
    if not ensure_warnings_cache_storage():
        return

    try:
        tmp_path = f"{WARNINGS_CACHE_FILE}.tmp"
        serializable_cache = dict(
            sorted(sent_warnings_cache.items(), key=lambda item: item[0])
        )
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(serializable_cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, WARNINGS_CACHE_FILE)
    except Exception as e:
        logging.error(
            f"Erro ao guardar cache de avisos ({WARNINGS_CACHE_FILE}): {e}"
        )


def get_location_name() -> str:
    """Resolve e cacheia o nome amigável da área alvo.

    Returns:
        str: Nome do distrito/área se resolvido; caso contrário devolve
            `AREA_ID`.
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
        Optional[str]: Caminho absoluto relativo à pasta de imagens ou
            ``None`` se não existir.
    """
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
    """Devolve o caminho do sticker associado ao tipo de aviso, se existir.

    Args:
        awareness_type: Tipo de aviso IPMA (ex.: "Trovoada", "Neve").

    Returns:
        Optional[str]: Caminho para o ficheiro do sticker na pasta de imagens,
            ou ``None`` caso não exista mapeamento ou o ficheiro não exista.
    """
    filename = WARNING_STICKERS.get(awareness_type)
    if not filename:
        return None
    path = os.path.join(IMAGES_DIR, filename)
    return path if os.path.exists(path) else None


def send_telegram_media(caption: str, image_path: str) -> None:
    """Envia media para o Telegram.

    Usa sticker para ficheiros ``.tgs`` e foto para os restantes formatos.

    Args:
        caption: Texto da mensagem a enviar (ou a reenviar como texto simples).
        image_path: Caminho local do ficheiro de media.

    Returns:
        None: Envia media para o Telegram e, em fallback, envia texto.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        ext = os.path.splitext(image_path)[1].lower()

        # O endpoint determina se o envio será sticker (.tgs) ou foto.
        if ext == '.tgs':
            method = "sendSticker"
            file_key = "sticker"
            has_caption = False
        else:
            method = "sendPhoto"
            file_key = "photo"
            has_caption = True

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
        data = {"chat_id": TELEGRAM_CHAT_ID}

        if has_caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"

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
    """Envia uma mensagem de texto simples para o Telegram.

    Args:
        msg: Conteúdo textual da mensagem em Markdown.

    Returns:
        None: Envia a mensagem para o chat configurado.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "HTML"
            },
            timeout=10
        )
    except Exception as e:
        logging.error(f"Erro envio texto: {e}")

# --- Jobs ---


def job_forecast() -> None:
    """Obtém previsão diária do IPMA e envia via Telegram.

    Envia com imagem quando existir um ficheiro local correspondente.

    Returns:
        None: Executa o envio da previsão diária para o chat configurado.
    """
    logging.info("A processar previsão diária...")
    try:
        resp = requests.get(f"{FORECAST_BASE}{GLOBAL_ID}.json", timeout=15)
        resp.raise_for_status()
        forecast = resp.json()['data'][1]

        weather_map = load_weather_types()
        weather_desc = weather_map.get(
            int(forecast['idWeatherType']),
            str(forecast['idWeatherType'])
        )

        wind_code = forecast['classWindSpeed']
        wind_desc = resolve_wind_desc(wind_code)

        location_name = get_location_name()

        try:
            pretty_date = datetime.strptime(
                forecast['forecastDate'],
                "%Y-%m-%d"
            ).strftime("%d-%m-%Y")
        except Exception:
            pretty_date = forecast['forecastDate']

        image_path = get_local_image_path(forecast['idWeatherType'])

        caption = (
            f"👀 <b>Previsão do tempo para amanhã:</b>\n"
            f"📅 <b>{html.escape(str(pretty_date))}</b>\n"
            f"\n"
            f"📍 Região: <b>{html.escape(str(location_name))}</b>\n"
            f"🌤️ {html.escape(str(weather_desc))}\n"
            f"🌡️ Min: {html.escape(str(forecast['tMin']))}ºC | Max: {html.escape(str(forecast['tMax']))}ºC\n"
            f"☔ Previsão de chuva: {html.escape(str(forecast['precipitaProb']))}%\n"
            f"💨 Vento de {html.escape(str(get_wind_dir_desc(forecast['predWindDir'])))} - "
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
    """Consulta avisos meteorológicos e envia novos alertas.

    Returns:
        None: Envia apenas avisos novos para o chat configurado e atualiza
            o cache local de avisos enviados.
    """
    logging.info("A verificar avisos...")
    try:
        removed = cleanup_sent_warnings_cache()
        if removed:
            logging.info(
                f"Limpeza de cache: removidas {removed} entradas expiradas."
            )

        if not WARNINGS_URL:
            return
        resp = requests.get(WARNINGS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        relevant = [
            w for w in data
            if w['idAreaAviso'] == AREA_ID and w['awarenessLevelID'] != 'green'
        ]

        if not relevant:
            if removed:
                save_sent_warnings_cache()
            return

        location_name = get_location_name()
        has_new_warning = False
        for w in relevant:
            start_date = w['startTime'].split('T')[0]
            w_id = (
                f"{w['idAreaAviso']}_{w['awarenessTypeName']}_"
                f"{w['awarenessLevelID']}_{start_date}"
            )
            if w_id not in sent_warnings_cache:
                try:
                    pretty_start = datetime.strptime(
                        w['startTime'],
                        "%Y-%m-%dT%H:%M:%S"
                    ).strftime("%H:%M %d-%m-%Y")
                except Exception:
                    pretty_start = w['startTime'].replace("T", " ")

                try:
                    pretty_end = datetime.strptime(
                        w['endTime'],
                        "%Y-%m-%dT%H:%M:%S"
                    ).strftime("%H:%M %d-%m-%Y")
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
                    f"⚠️ <b>AVISO IPMA:</b>\n"
                    f"\n"
                    f"📍 Região: <b>{html.escape(str(location_name))}</b>\n"
                    f"🔔 {html.escape(str(w['awarenessTypeName']))}\n"
                    f"{html.escape(str(pretty_awareness))}\n"
                    f"🕒 {html.escape(str(pretty_start))} até {html.escape(str(pretty_end))}\n"
                    f"\n"
                    f"📝 {html.escape(str(w['text']))}\n"
                    f"\n"
                    f"🌍 Fonte: <a href=\"https://www.ipma.pt/pt/otempo/"
                    f"prev-sam/?p={html.escape(str(AREA_ID), quote=True)}\">ipma.pt</a>"
                )
                sticker_path = get_warning_sticker_path(w['awarenessTypeName'])
                if sticker_path:
                    send_telegram_media(msg, sticker_path)
                else:
                    send_message_text(msg)
                sent_warnings_cache[w_id] = get_warning_expiry_ts(
                    w.get('endTime', '')
                )
                has_new_warning = True
                logging.info(f"Aviso enviado: {w_id}")
            else:
                logging.info(f"Aviso já enviado: {w_id}")

        if has_new_warning or removed:
            save_sent_warnings_cache()
    except Exception as e:
        logging.error(f"Erro avisos: {e}")

# --- Main ---


if __name__ == "__main__":
    logging.info("Bot Iniciado.")

    if not os.path.exists(IMAGES_DIR):
        logging.error(f"❌ Erro: Pasta '{IMAGES_DIR}' não encontrada.")
        exit()

    get_location_name()
    load_sent_warnings_cache()

    schedule.every(CHECK_INTERVAL).minutes.do(job_warnings)
    schedule.every().day.at(FORECAST_TIME).do(job_forecast)

    while True:
        schedule.run_pending()
        time.sleep(1)
