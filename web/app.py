import os
from flask import Flask, render_template, request, redirect, url_for, flash
from modules.db import get_db
from dotenv import set_key, load_dotenv

app = Flask(__name__)
app.secret_key = "super_secret_key_change_in_prod"

@app.route('/')
def dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as count FROM feeds WHERE status = 'active'")
    active_feeds = c.fetchone()['count']
    
    c.execute("SELECT COUNT(*) as count FROM articles")
    total_articles = c.fetchone()['count']
    
    conn.close()
    return render_template('dashboard.html', active_feeds=active_feeds, total_articles=total_articles)

@app.route('/feeds', methods=['GET', 'POST'])
def feeds():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        url = request.form.get('url')
        if name and url:
            try:
                c.execute("INSERT INTO feeds (name, url) VALUES (?, ?)", (name, url))
                conn.commit()
                flash('Feed adicionado com sucesso!')
            except Exception as e:
                flash(f'Erro ao adicionar feed: {e}', 'error')
        return redirect(url_for('feeds'))
        
    c.execute("SELECT * FROM feeds")
    feeds_list = c.fetchall()
    conn.close()
    return render_template('feeds.html', feeds=feeds_list)

@app.route('/feeds/delete/<int:feed_id>', methods=['POST'])
def delete_feed(feed_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()
    flash('Feed removido.')
    return redirect(url_for('feeds'))

@app.route('/logs')
def logs():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 100")
    logs_list = c.fetchall()
    conn.close()
    return render_template('logs.html', logs=logs_list)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    env_path = '.env'
    if request.method == 'POST':
        rss_interval = request.form.get('rss_interval')
        chat_id = request.form.get('chat_id')
        bot_token = request.form.get('bot_token')
        
        if rss_interval: set_key(env_path, 'RSS_CHECK_INTERVAL_MINUTES', rss_interval)
        if chat_id: set_key(env_path, 'CHAT_ID', chat_id)
        if bot_token: set_key(env_path, 'BOT_TOKEN', bot_token)
        
        load_dotenv(override=True)
        flash('Configurações guardadas!')
        return redirect(url_for('settings'))
        
    rss_interval = os.environ.get('RSS_CHECK_INTERVAL_MINUTES', '30')
    chat_id = os.environ.get('CHAT_ID', '')
    bot_token = os.environ.get('BOT_TOKEN', '')
    
    return render_template('settings.html', rss_interval=rss_interval, chat_id=chat_id, bot_token=bot_token)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("WEB_PORT", 8080)), debug=True)
