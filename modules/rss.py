import feedparser
import logging
import requests
import hashlib
from difflib import SequenceMatcher
from datetime import datetime
from modules.db import get_db
from modules.telegram_bot import send_message_text

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def generate_hash(title, link):
    raw = f"{title}|{link}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def is_similar_to_recent(c, title, threshold=0.8):
    # Fetch recent titles to compare
    c.execute("SELECT title FROM articles ORDER BY id DESC LIMIT 50")
    recent_titles = [row['title'] for row in c.fetchall()]
    for rt in recent_titles:
        if similarity(title.lower(), rt.lower()) > threshold:
            return True
    return False

def process_feeds():
    logging.info("A iniciar leitura de feeds RSS...")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, url, name, last_checked FROM feeds WHERE status = 'active'")
    feeds = c.fetchall()

    new_articles_count = 0

    for feed in feeds:
        is_first_run = (feed['last_checked'] is None)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'application/rss+xml, application/rdf+xml, application/atom+xml, application/xml, text/xml, */*;q=0.9',
                'Accept-Language': 'pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            resp = requests.get(feed['url'], headers=headers, timeout=15)
            
            # Se for 403, pode ser a Cloudflare.
            if resp.status_code != 200:
                logging.warning(f"Erro ao processar feed {feed['name']}: HTTP {resp.status_code}")
                continue
                
            # Correção de sintaxe para sites (como o Imediato) que enviam XML mal formatado
            raw_content = resp.content.decode('utf-8', errors='ignore')
            raw_content = raw_content.replace('"xmlns:', '" xmlns:')
                
            parsed = feedparser.parse(raw_content)
            if parsed.bozo and not parsed.entries:
                logging.warning(f"Erro ao processar feed {feed['name']} ({feed['url']}): {parsed.bozo_exception}")
                continue

            feed_title = parsed.feed.get('title', feed['name'])

            for entry in parsed.entries:
                title = entry.get('title', '(Sem título)')
                link = entry.get('link', '')
                art_hash = generate_hash(title, link)

                # Check if exact article exists
                c.execute("SELECT id FROM articles WHERE article_hash = ?", (art_hash,))
                if c.fetchone():
                    continue

                # Check similarity
                if is_similar_to_recent(c, title):
                    logging.info(f"Artigo ignorado por similaridade: {title}")
                    # Registar para não voltar a verificar
                    c.execute(
                        "INSERT INTO articles (feed_id, title, link, article_hash, published_at) VALUES (?, ?, ?, ?, ?)",
                        (feed['id'], title, link, art_hash, datetime.now())
                    )
                    continue

                # Guardar na Base de Dados
                c.execute(
                    "INSERT INTO articles (feed_id, title, link, article_hash, published_at) VALUES (?, ?, ?, ?, ?)",
                    (feed['id'], title, link, art_hash, datetime.now())
                )

                if is_first_run:
                    logging.info(f"Artigo ignorado (modo silencioso 1º arranque de {feed_title}): {title}")
                else:
                    logging.info(f"Novo artigo de {feed_title}: {title}")
                    msg = f"📰 <b>{feed_title}</b>\n{title}\n{link}"
                    send_message_text(msg)
                    new_articles_count += 1

            # Update last_checked
            c.execute("UPDATE feeds SET last_checked = ? WHERE id = ?", (datetime.now(), feed['id']))
            conn.commit()
            
        except Exception as e:
            logging.error(f"Erro a processar o feed {feed['name']}: {e}")

    conn.close()
    logging.info(f"Leitura concluída. {new_articles_count} novos artigos processados.")

