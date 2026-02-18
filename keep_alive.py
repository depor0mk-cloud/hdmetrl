from flask import Flask
from threading import Thread
app = Flask('')
@app.route('/')
@app.route('/health')
def home(): return "✅ Бот работает!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()
