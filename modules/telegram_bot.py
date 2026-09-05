import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

def get_telegram_config():
    # Carrega do env atual
    return os.getenv("BOT_TOKEN"), os.getenv("CHAT_ID")

def send_telegram_media(caption: str, image_path: str) -> None:
    token, chat_id = get_telegram_config()
    if not token or not chat_id:
        logging.warning("Telegram token ou chat_id não configurados.")
        return

    try:
        ext = os.path.splitext(image_path)[1].lower()
        if ext == '.tgs':
            method = "sendSticker"
            file_key = "sticker"
            has_caption = False
        else:
            method = "sendPhoto"
            file_key = "photo"
            has_caption = True

        url = f"https://api.telegram.org/bot{token}/{method}"
        data = {"chat_id": chat_id}

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
    token, chat_id = get_telegram_config()
    if not token or not chat_id:
        logging.warning("Telegram token ou chat_id não configurados.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            },
            timeout=10
        )
    except Exception as e:
        logging.error(f"Erro envio texto: {e}")
