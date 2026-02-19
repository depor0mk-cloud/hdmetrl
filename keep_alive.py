from flask import Flask
from threading import Thread
import logging

app = Flask('')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # Отключаем лишние логи

@app.route('/')
@app.route('/health')
def home():
    return "✅ Бот работает!"

def run():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
