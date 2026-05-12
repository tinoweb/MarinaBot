from flask import Flask
from dotenv import load_dotenv
import os

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key')
    
    # Inicializa o banco de dados
    from app.config.database import init_db
    init_db()
    
    # Registra os blueprints
    from app.controllers.main_controller import main_bp
    from app.controllers.webhook_controller import webhook_bp
    from app.controllers.admin_controller import admin_bp
    from app.controllers.whatsapp_controller import whatsapp_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(whatsapp_bp)
    
    return app
