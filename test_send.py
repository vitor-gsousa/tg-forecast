import os
import html
from dotenv import load_dotenv
import forecast

load_dotenv()

# Test strings with problematic characters
location_name = "S. Brás de Alportel <test>"
w_text = "Aviso: <ventos fortes> & 'chuva' e \"trovoada\"!"
AREA_ID = "BGC\"&<"
w_type = "Vento"
pretty_start = "10:00"
pretty_end = "18:00"
pretty_awareness = "Amarelo"

msg = (
    f"⚠️ <b>AVISO DE TESTE IPMA:</b>\n"
    f"\n"
    f"📍 Região: <b>{html.escape(str(location_name))}</b>\n"
    f"🔔 {html.escape(str(w_type))}\n"
    f"{html.escape(str(pretty_awareness))}\n"
    f"🕒 {html.escape(str(pretty_start))} até {html.escape(str(pretty_end))}\n"
    f"\n"
    f"📝 {html.escape(str(w_text))}\n"
    f"\n"
    f"🌍 Fonte: <a href=\"https://www.ipma.pt/pt/otempo/"
    f"prev-sam/?p={html.escape(str(AREA_ID), quote=True)}\">ipma.pt</a>"
)

try:
    forecast.send_message_text(msg)
    print("Teste enviado com sucesso.")
except Exception as e:
    print(f"Erro no teste: {e}")
