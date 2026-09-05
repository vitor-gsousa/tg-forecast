import os
import time
import threading
import schedule
import logging
from dotenv import load_dotenv

from modules.db import init_db, DBLogHandler
from modules.rss import process_feeds
from modules.weather import job_forecast, job_warnings
from web.app import app

# Configuração global de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
logger.addHandler(DBLogHandler())

def run_schedule():
    logging.info("Agendador (Schedule) iniciado.")
    while True:
        schedule.run_pending()
        time.sleep(1)

def run_web():
    port = int(os.environ.get("WEB_PORT", 8080))
    logging.info(f"Frontend Web iniciado na porta {port}.")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    load_dotenv()
    init_db()
    
    # Agendamento RSS
    rss_interval = int(os.environ.get("RSS_CHECK_INTERVAL_MINUTES", 30))
    schedule.every(rss_interval).minutes.do(process_feeds)
    
    # Agendamento IPMA (mantendo as configs do weather.py via .env)
    check_interval = int(os.environ.get("CHECK_INTERVAL_MINUTES", 60))
    forecast_time = os.environ.get("FORECAST_TIME", "20:30")
    
    schedule.every(check_interval).minutes.do(job_warnings)
    schedule.every().day.at(forecast_time).do(job_forecast)
    
    # Inicia a thread do agendador
    t = threading.Thread(target=run_schedule, daemon=True)
    t.start()
    
    # Inicia a app web na thread principal
    run_web()
