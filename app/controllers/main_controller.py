from flask import Blueprint, render_template, redirect, url_for

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Rota principal que exibe a landing page com botão para WhatsApp"""
    return render_template('index.html')

@main_bp.route('/sobre')
def about():
    """Página sobre o serviço"""
    return render_template('about.html')

@main_bp.route('/termos')
def terms():
    """Página de termos e condições (LGPD)"""
    return render_template('terms.html')
