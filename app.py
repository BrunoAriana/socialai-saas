import os
import random
import re
import textwrap
import base64
import json
import urllib.request
import secrets
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, send_file, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text, inspect
from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from authlib.integrations.flask_client import OAuth
except Exception:
    OAuth = None

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / 'instance'
PRIVATE_DIR = Path(os.getenv('UPLOAD_FOLDER', BASE_DIR / 'generated_private'))

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'troque-esta-chave-em-producao')
raw_db_url = os.getenv('DATABASE_URL', f"sqlite:///{INSTANCE_DIR / 'socialai.db'}")
# Render/Railway às vezes fornecem postgres://; SQLAlchemy moderno espera postgresql://
if raw_db_url.startswith('postgres://'):
    raw_db_url = raw_db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = str(PRIVATE_DIR)
app.config['PIX_KEY'] = os.getenv('PIX_KEY', 'configure-sua-chave-pix')
app.config['ADMIN_EMAIL'] = os.getenv('ADMIN_EMAIL', 'admin@seudominio.com').lower()
app.config['ENABLE_FAKE_PAYMENT'] = os.getenv('ENABLE_FAKE_PAYMENT', '0') == '1'
app.config['FREE_PREVIEW_LIMIT'] = int(os.getenv('FREE_PREVIEW_LIMIT', '30'))
app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID', '')
app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET', '')
app.config['SMTP_HOST'] = os.getenv('SMTP_HOST', '')
app.config['SMTP_PORT'] = int(os.getenv('SMTP_PORT', '587'))
app.config['SMTP_USER'] = os.getenv('SMTP_USER', '')
app.config['SMTP_PASSWORD'] = os.getenv('SMTP_PASSWORD', '')
app.config['SMTP_FROM'] = os.getenv('SMTP_FROM', os.getenv('SMTP_USER', 'no-reply@seudominio.com'))
app.config['SMTP_USE_TLS'] = os.getenv('SMTP_USE_TLS', '1') == '1'

db = SQLAlchemy(app)
oauth = OAuth(app) if OAuth else None
if oauth and app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET']:
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    google_id = db.Column(db.String(255), nullable=True, index=True)
    auth_provider = db.Column(db.String(30), default='email', nullable=False)
    credits = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_admin(self):
        return self.email.lower() == app.config['ADMIN_EMAIL']




class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_valid(self):
        return not self.used_at and self.expires_at > datetime.utcnow()

class Brand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    business_name = db.Column(db.String(160), nullable=False)
    niche = db.Column(db.String(120), nullable=False)
    audience = db.Column(db.String(240), nullable=False)
    offer = db.Column(db.String(240), nullable=False)
    tone = db.Column(db.String(80), default='Profissional')
    primary_color = db.Column(db.String(20), default='#1f2937')
    secondary_color = db.Column(db.String(20), default='#f7efe6')
    accent_color = db.Column(db.String(20), default='#b88a44')
    instagram = db.Column(db.String(80), default='@suamarca')


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(220), nullable=False)
    subtitle = db.Column(db.String(220), nullable=True)
    caption = db.Column(db.Text, nullable=False)
    hashtags = db.Column(db.String(400), nullable=False)
    format = db.Column(db.String(50), default='feed')
    style = db.Column(db.String(50), default='premium')
    objective = db.Column(db.String(80), default='interesse')
    status = db.Column(db.String(50), default='draft')
    scheduled_at = db.Column(db.DateTime, nullable=True)
    image_file = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    package_key = db.Column(db.String(50), nullable=False)
    package_name = db.Column(db.String(120), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default='pending')
    proof_text = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)


class DownloadLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CommercialPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    plan_type = db.Column(db.String(30), default='package')  # package ou subscription
    credits = db.Column(db.Integer, nullable=False, default=0)
    bonus_credits = db.Column(db.Integer, nullable=False, default=0)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    original_amount_cents = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(255), nullable=False, default='')
    badge = db.Column(db.String(80), nullable=True)
    cta = db.Column(db.String(80), default='Comprar')
    featured = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def total_credits(self):
        return int(self.credits or 0) + int(self.bonus_credits or 0)


class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)


DEFAULT_PLANS = [
    {
        'key': 'teste', 'name': 'Teste', 'plan_type': 'package', 'credits': 5, 'bonus_credits': 0,
        'amount_cents': 1990, 'original_amount_cents': None, 'description': '5 artes finais para experimentar sem compromisso.',
        'badge': 'Entrada', 'cta': 'Comprar créditos', 'featured': False, 'sort_order': 10
    },
    {
        'key': 'start_mensal', 'name': 'Start Mensal', 'plan_type': 'subscription', 'credits': 30, 'bonus_credits': 10,
        'amount_cents': 4990, 'original_amount_cents': None, 'description': 'Ideal para autônomos e pequenos negócios manterem presença constante.',
        'badge': 'Mais acessível', 'cta': 'Assinar plano', 'featured': False, 'sort_order': 20
    },
    {
        'key': 'pro_lancamento', 'name': 'Pro Lançamento', 'plan_type': 'subscription', 'credits': 80, 'bonus_credits': 30,
        'amount_cents': 6990, 'original_amount_cents': 9990, 'description': 'Plano promocional para postar com frequência e padrão profissional.',
        'badge': 'Mais vendido', 'cta': 'Começar com promoção', 'featured': True, 'sort_order': 30
    },
    {
        'key': 'premium_mensal', 'name': 'Premium Mensal', 'plan_type': 'subscription', 'credits': 200, 'bonus_credits': 100,
        'amount_cents': 19990, 'original_amount_cents': None, 'description': 'Volume alto para social medias, agências e múltiplas marcas.',
        'badge': 'Agência', 'cta': 'Assinar Premium', 'featured': False, 'sort_order': 40
    },
    {
        'key': 'agencia_avulso', 'name': 'Agência Avulso', 'plan_type': 'package', 'credits': 100, 'bonus_credits': 0,
        'amount_cents': 17990, 'original_amount_cents': None, 'description': 'Pacote grande de créditos sem mensalidade.',
        'badge': 'Avulso', 'cta': 'Comprar pacote', 'featured': False, 'sort_order': 50
    },
]

DEFAULT_SETTINGS = {
    'site_name': 'SocialAI Pro',
    'hero_title': 'Posts profissionais, legendas prontas e artes com cara de marca premium.',
    'hero_subtitle': 'Gere prévias, escolha as melhores e baixe a arte final somente quando tiver créditos.',
    'sales_banner': 'Oferta de lançamento: Plano Pro com preço promocional para os primeiros clientes.',
    'pix_key': os.getenv('PIX_KEY', 'configure-sua-chave-pix'),
    'whatsapp': '',
    'premium_ai_enabled': '1',
    'ai_premium_cost': os.getenv('AI_PREMIUM_COST', '3'),
    'openai_text_model': os.getenv('OPENAI_TEXT_MODEL', 'gpt-4.1-mini'),
    'openai_image_model': os.getenv('OPENAI_IMAGE_MODEL', 'gpt-image-1'),
}




def is_google_login_enabled():
    return bool(oauth and app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'))


def send_email_message(to_email, subject, body):
    """Envia e-mail por SMTP quando configurado. Retorna True se enviou."""
    if not app.config.get('SMTP_HOST'):
        app.logger.warning('SMTP não configurado. E-mail não enviado para %s. Conteúdo: %s', to_email, body)
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = app.config['SMTP_FROM']
    msg['To'] = to_email
    msg.set_content(body)
    with smtplib.SMTP(app.config['SMTP_HOST'], app.config['SMTP_PORT'], timeout=20) as server:
        if app.config.get('SMTP_USE_TLS'):
            server.starttls()
        if app.config.get('SMTP_USER'):
            server.login(app.config['SMTP_USER'], app.config['SMTP_PASSWORD'])
        server.send_message(msg)
    return True


def create_password_reset_link(user):
    raw_token = secrets.token_urlsafe(40)
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=generate_password_hash(raw_token),
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    db.session.add(reset)
    db.session.commit()
    return url_for('reset_password', token=raw_token, _external=True)


def find_password_reset_token(raw_token):
    active_tokens = PasswordResetToken.query.filter(
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > datetime.utcnow()
    ).order_by(PasswordResetToken.created_at.desc()).limit(50).all()
    for item in active_tokens:
        if check_password_hash(item.token_hash, raw_token):
            return item
    return None


def ensure_schema_updates():
    """Pequena migração automática para bancos já publicados no Render."""
    inspector = inspect(db.engine)
    try:
        cols = {c['name'] for c in inspector.get_columns('user')}
    except Exception:
        return
    dialect = db.engine.dialect.name
    stmts = []
    if 'google_id' not in cols:
        if dialect == 'postgresql':
            stmts.append('ALTER TABLE "user" ADD COLUMN google_id VARCHAR(255)')
        else:
            stmts.append('ALTER TABLE user ADD COLUMN google_id VARCHAR(255)')
    if 'auth_provider' not in cols:
        if dialect == 'postgresql':
            stmts.append('ALTER TABLE "user" ADD COLUMN auth_provider VARCHAR(30) DEFAULT \'email\' NOT NULL')
        else:
            stmts.append("ALTER TABLE user ADD COLUMN auth_provider VARCHAR(30) DEFAULT 'email' NOT NULL")
    for stmt in stmts:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            app.logger.warning('Migração ignorada/falhou: %s - %s', stmt, exc)

def seed_commercial_defaults():
    for data in DEFAULT_PLANS:
        if not CommercialPlan.query.filter_by(key=data['key']).first():
            db.session.add(CommercialPlan(**data))
    for key, value in DEFAULT_SETTINGS.items():
        if not SiteSetting.query.filter_by(key=key).first():
            db.session.add(SiteSetting(key=key, value=value))
    db.session.commit()


def get_setting(key, default=''):
    item = SiteSetting.query.filter_by(key=key).first()
    return item.value if item and item.value is not None else default


def set_setting(key, value):
    item = SiteSetting.query.filter_by(key=key).first()
    if not item:
        item = SiteSetting(key=key)
        db.session.add(item)
    item.value = value


def active_plans():
    return CommercialPlan.query.filter_by(active=True).order_by(CommercialPlan.sort_order.asc(), CommercialPlan.amount_cents.asc()).all()


OBJECTIVES = {
    'interesse': 'Gerar interesse',
    'direct': 'Gerar direct',
    'autoridade': 'Construir autoridade',
    'educativo': 'Educar o público',
    'oferta': 'Vender uma oferta',
}

STYLES = {
    'premium': 'Premium / elegante',
    'minimal': 'Minimalista',
    'bold': 'Chamativo',
    'editorial': 'Editorial / autoridade',
    'luxo': 'Luxo / sofisticado',
    'saude': 'Saúde / clínico premium',
    'vendedor': 'Comercial / vendedor',
}


def format_money(cents):
    return f"R$ {cents/100:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def parse_money_to_cents(value):
    text = str(value or '').strip().replace('R$', '').replace(' ', '')
    if not text:
        return 0
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    return int(round(float(text) * 100))


@app.context_processor
def inject_globals():
    return {
        'current_user': current_user(),
        'format_money': format_money,
        'styles': STYLES,
        'objectives': OBJECTIVES,
        'get_setting': get_setting,
        'site_name': get_setting('site_name', 'SocialAI Pro') if 'site_setting' in db.metadata.tables else 'SocialAI Pro',
        'google_login_enabled': is_google_login_enabled(),
    }


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user.is_admin:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None


def get_brand():
    return Brand.query.filter_by(user_id=session.get('user_id')).first()


def clean_tag(text):
    text = text.lower()
    accents = str.maketrans('áàâãäéèêëíìîïóòôõöúùûüçñ', 'aaaaaeeeeiiiiooooouuuucn')
    text = text.translate(accents)
    return ''.join(ch for ch in text if ch.isalnum())[:28]



def openai_client():
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key or not OpenAI:
        return None
    return OpenAI(api_key=api_key)


def json_from_text(text):
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?', '', cleaned).strip()
    cleaned = re.sub(r'```$', '', cleaned).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r'\{.*\}', cleaned, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
    return None


def ai_text_pack(brand, topic, objective, style):
    """Gera copy estratégica via API. Se não houver chave, usa o motor local."""
    client = openai_client()
    if not client:
        return None
    model = get_setting('openai_text_model', os.getenv('OPENAI_TEXT_MODEL', 'gpt-4.1-mini'))
    prompt = f"""
Você é estrategista sênior de marketing para redes sociais no Brasil.
Crie um post premium para Instagram com alta chance de gerar interesse, direct ou venda.
Responda SOMENTE em JSON válido, sem markdown.

Dados da marca:
- Nome: {brand.business_name}
- Nicho: {brand.niche}
- Público: {brand.audience}
- Oferta: {brand.offer}
- Tom de voz: {brand.tone}
- Instagram: {brand.instagram}

Pedido:
- Tema: {topic}
- Objetivo: {OBJECTIVES.get(objective, objective)}
- Estilo visual: {STYLES.get(style, style)}

JSON obrigatório:
{{
  "title": "headline curta, forte, com no máximo 70 caracteres",
  "subtitle": "subheadline persuasivo com no máximo 95 caracteres",
  "body": "texto curto para entrar na arte, com no máximo 125 caracteres",
  "cta": "chamada curta com no máximo 34 caracteres",
  "caption": "legenda completa em português, com quebra de linhas, educativa e persuasiva, sem promessas milagrosas",
  "hashtags": "8 a 12 hashtags relevantes em português"
}}
""".strip()
    try:
        # Preferência: Responses API. Fallback para Chat Completions se o SDK/conta não suportar.
        try:
            resp = client.responses.create(model=model, input=prompt)
            text = getattr(resp, 'output_text', None) or ''
        except Exception:
            resp = client.chat.completions.create(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.7,
            )
            text = resp.choices[0].message.content
        data = json_from_text(text)
        if not data:
            return None
        return {
            'title': str(data.get('title') or strategic_title(topic, objective, brand))[:180],
            'subtitle': str(data.get('subtitle') or make_subtitle(topic, objective, brand))[:220],
            'body': str(data.get('body') or 'Conteúdo estratégico para uma decisão mais segura.')[:220],
            'cta': str(data.get('cta') or ('Fale conosco' if objective == 'oferta' else 'Agende sua avaliação'))[:60],
            'caption': str(data.get('caption') or generate_caption(brand, topic, objective)),
            'hashtags': str(data.get('hashtags') or make_hashtags(brand, topic)),
        }
    except Exception as exc:
        print('OpenAI text generation failed:', exc)
        return None


def build_visual_prompt(brand, topic, objective, style, fmt):
    palette = f"primary {brand.primary_color}, secondary {brand.secondary_color}, accent {brand.accent_color}"
    format_desc = 'vertical Instagram story, 9:16' if fmt == 'story' else 'square Instagram feed post, 1:1'
    niche = brand.niche.lower()
    subject = 'premium editorial brand campaign background'
    if any(k in niche for k in ['estética','estetica','beleza','clínica','clinica','dermato','odont','saúde','saude','nutri','psicolog']):
        subject = 'professional lifestyle photo of a confident adult client in a premium clinic atmosphere, healthy natural look, elegant lighting'
    elif any(k in niche for k in ['advoc','juríd','jurid']):
        subject = 'premium law office atmosphere, elegant professional portrait style, sophisticated corporate visual'
    elif any(k in niche for k in ['imobili','corret','arquitet']):
        subject = 'premium real estate and architecture atmosphere, elegant interior, natural light, sophisticated editorial style'
    elif any(k in niche for k in ['restaurante','comida','gastron']):
        subject = 'premium food and restaurant campaign background, elegant table styling, appetizing editorial photo'
    return f"""
Create a premium commercial visual asset for a Brazilian social media SaaS to be used as the background/hero image of an Instagram post.
IMPORTANT: do not include any text, letters, words, numbers, logo, watermark, captions, UI, posters or readable typography in the image.
Format: {format_desc}.
Business niche: {brand.niche}. Campaign theme: {topic}. Objective: {OBJECTIVES.get(objective, objective)}. Visual style: {STYLES.get(style, style)}.
Scene: {subject}.
Color direction: {palette}; use refined neutrals, soft light, luxurious but credible composition, high-end advertising photography, polished, modern, premium, realistic.
Leave clean negative space on the left side or top-left area for text overlay. No exaggerated beauty filters, no medical claims, no before/after, no explicit procedures.
""".strip()


def create_ai_visual_asset(brand, topic, objective, style, fmt):
    client = openai_client()
    if not client:
        return None
    model = get_setting('openai_image_model', os.getenv('OPENAI_IMAGE_MODEL', 'gpt-image-1'))
    size = '1024x1536' if fmt == 'story' else '1024x1024'
    prompt = build_visual_prompt(brand, topic, objective, style, fmt)
    try:
        try:
            result = client.images.generate(model=model, prompt=prompt, size=size, quality='high', n=1)
        except TypeError:
            result = client.images.generate(model=model, prompt=prompt, size=size, n=1)
        item = result.data[0]
        if getattr(item, 'b64_json', None):
            raw = base64.b64decode(item.b64_json)
        elif getattr(item, 'url', None):
            with urllib.request.urlopen(item.url, timeout=60) as response:
                raw = response.read()
        else:
            return None
        return Image.open(BytesIO(raw)).convert('RGB')
    except Exception as exc:
        print('OpenAI image generation failed:', exc)
        return None


def fit_cover(img, size):
    w, h = size
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return resized.crop((left, top, left + w, top + h))

def strategic_title(topic, objective, brand):
    niche = brand.niche.lower()
    bank = {
        'interesse': [
            f'Você precisa da estratégia certa para {topic.lower()}',
            f'O erro que trava seus resultados',
            f'Antes de investir, leia isso',
        ],
        'direct': [
            f'Qual caminho faz sentido para você?',
            f'Me envie “QUERO” no direct',
            f'O próximo passo começa aqui',
        ],
        'autoridade': [
            f'O que ninguém te explica',
            f'Menos improviso. Mais estratégia.',
            f'Como analisar antes de decidir',
        ],
        'educativo': [
            f'3 sinais para rever sua estratégia',
            f'Guia rápido para decidir melhor',
            f'O básico bem feito funciona',
        ],
        'oferta': [
            f'Uma solução com estratégia',
            f'Chegou a hora de buscar resultado',
            f'Sua oportunidade de agir com clareza',
        ],
    }
    return random.choice(bank.get(objective, bank['interesse']))


def make_subtitle(topic, objective, brand):
    bank = {
        'interesse': 'Um bom resultado começa com diagnóstico, estratégia e execução personalizada.',
        'direct': 'Responda no direct e receba uma orientação inicial para o seu caso.',
        'autoridade': 'Decisões melhores nascem de clareza, método e consistência.',
        'educativo': 'Entenda o que realmente importa antes de tomar uma decisão.',
        'oferta': f'Conheça uma forma mais estratégica de contratar {brand.offer.lower()}.',
    }
    return bank.get(objective, bank['interesse'])


def generate_caption(brand, topic, objective):
    hook = {
        'interesse': f'Nem sempre o problema é falta de esforço. Muitas vezes, falta a estratégia certa para {topic.lower()}.',
        'direct': f'Se você quer melhorar {topic.lower()}, o primeiro passo é entender o que realmente está travando seu resultado.',
        'autoridade': f'Existe uma grande diferença entre fazer por tentativa e erro e seguir um método para {topic.lower()}.',
        'educativo': f'Antes de tomar qualquer decisão sobre {topic.lower()}, vale entender alguns pontos importantes.',
        'oferta': f'Para quem busca uma solução mais clara para {topic.lower()}, este é o momento de agir com estratégia.',
    }.get(objective)
    body = (
        f'Na {brand.business_name}, nós olhamos para o contexto de {brand.audience}, identificamos prioridades e indicamos o caminho mais adequado. '
        f'O objetivo não é entregar algo genérico, mas criar uma decisão mais segura, profissional e alinhada ao que você precisa.'
    )
    ctas = {
        'interesse': 'Salve este post e me chame quando quiser entender o melhor caminho para o seu caso.',
        'direct': 'Me envie “QUERO” no direct e eu te explico o próximo passo.',
        'autoridade': 'Siga o perfil para ver mais conteúdos estratégicos como este.',
        'educativo': 'Salve para consultar depois e envie para alguém que precisa ver isso.',
        'oferta': 'Fale conosco e veja como começar ainda esta semana.',
    }
    return f"{hook}\n\n{body}\n\n{ctas.get(objective)}"


def make_hashtags(brand, topic):
    base = [brand.niche, brand.business_name, topic, 'conteudoprofissional', 'marketingdigital', 'empreendedorismo', 'resultados', 'estrategia']
    tags = ['#' + clean_tag(x) for x in base if clean_tag(x)]
    return ' '.join(dict.fromkeys(tags))


def hex_to_rgb(hex_color, fallback=(31, 41, 55)):
    try:
        c = (hex_color or '').strip().lstrip('#')
        return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return fallback


def rgb_to_hex(rgb):
    return '#%02x%02x%02x' % rgb


def blend(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def contrast_rgb(rgb):
    lum = (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000
    return (17, 24, 39) if lum > 160 else (255, 255, 255)


def font(size, bold=False, serif=False):
    candidates = []
    if serif:
        candidates += [
            '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
            '/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf',
        ]
    candidates += [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_wrapped(draw, text, xy, max_width, fnt, fill, line_gap=10, max_lines=None):
    words = text.split()
    lines, current = [], ''
    for word in words:
        test = (current + ' ' + word).strip()
        box = draw.textbbox((0, 0), test, font=fnt)
        if box[2] - box[0] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if max_lines:
        lines = lines[:max_lines]
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        bbox = draw.textbbox((x, y), line, font=fnt)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def gradient_background(size, c1, c2):
    w, h = size
    img = Image.new('RGB', size, c1)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        row = blend(c1, c2, t)
        for x in range(w):
            px[x, y] = row
    return img


def safe_filename(post_id):
    return f'post_{post_id}_{int(datetime.utcnow().timestamp())}_{random.randint(1000, 9999)}.png'


def draw_lotus(draw, cx, cy, color):
    # Ícone simples, sem fonte externa.
    for dx in [-34, 0, 34]:
        draw.ellipse([cx + dx - 24, cy - 36, cx + dx + 24, cy + 24], outline=color, width=3)
    draw.arc([cx - 70, cy - 20, cx + 70, cy + 55], 200, 340, fill=color, width=3)
    draw.ellipse([cx - 5, cy - 70, cx + 5, cy - 60], fill=color)


def generate_image(post, brand):
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    feed = post.format == 'feed'
    w, h = (1080, 1080) if feed else (1080, 1920)
    primary = hex_to_rgb(brand.primary_color, (55, 37, 26))
    secondary = hex_to_rgb(brand.secondary_color, (247, 239, 230))
    accent = hex_to_rgb(brand.accent_color, (184, 138, 68))
    dark = (38, 28, 22)
    cream = blend(secondary, (255, 255, 255), 0.45)

    img = gradient_background((w, h), cream, blend(secondary, (255, 255, 255), 0.05))
    draw = ImageDraw.Draw(img)

    # Elementos visuais premium/abstratos.
    for i, r in enumerate([520, 760, 980]):
        box = [w - r // 2, 80 + i * 70, w + r // 2, 80 + i * 70 + r]
        draw.ellipse(box, outline=blend(accent, (255, 255, 255), 0.74), width=3)
    draw.rounded_rectangle([w * 0.57, h * 0.16, w * 1.05, h * 0.82], radius=55, fill=blend(accent, secondary, 0.76))
    draw.rounded_rectangle([w * 0.61, h * 0.20, w * 0.98, h * 0.72], radius=46, fill=blend(secondary, (255,255,255), .30))
    # Foto/hero placeholder refinado: silhueta editorial abstrata, substituível por imagem real em versão futura.
    face_c = blend((232, 186, 148), secondary, .20)
    hair_c = blend(primary, (25, 18, 14), .25)
    cx = int(w * 0.80)
    cy = int(h * (0.40 if feed else 0.34))
    scale = 1 if feed else 1.25
    draw.ellipse([cx-170*scale, cy-250*scale, cx+135*scale, cy+190*scale], fill=hair_c)
    draw.ellipse([cx-125*scale, cy-185*scale, cx+115*scale, cy+130*scale], fill=face_c)
    draw.ellipse([cx-62*scale, cy-35*scale, cx-45*scale, cy-20*scale], fill=dark)
    draw.ellipse([cx+38*scale, cy-35*scale, cx+55*scale, cy-20*scale], fill=dark)
    draw.arc([cx-45*scale, cy+22*scale, cx+52*scale, cy+82*scale], 10, 170, fill=dark, width=4)
    draw.line([cx-18*scale, cy-5*scale, cx-30*scale, cy+30*scale], fill=blend(dark, face_c, .45), width=3)
    draw.ellipse([cx+110*scale, cy-20*scale, cx+140*scale, cy+15*scale], outline=accent, width=6)
    draw.rounded_rectangle([cx-105*scale, cy+145*scale, cx+160*scale, cy+360*scale], radius=80, fill=face_c)

    left = 76
    top = 78 if feed else 120
    draw_lotus(draw, left + 48, top + 40, accent)
    draw.line([left + 135, top + 45, left + 430, top + 45], fill=accent, width=2)

    headline = post.title.upper()
    title_size = 58 if feed else 70
    if len(headline) > 58:
        title_size -= 8
    y = top + 135
    y = draw_wrapped(draw, headline, (left, y), int(w * 0.50), font(title_size, bold=True, serif=True), dark, line_gap=12, max_lines=4 if feed else 6)

    y += 18
    sub = (post.subtitle or '').upper()
    y = draw_wrapped(draw, sub, (left, y), int(w * 0.52), font(34 if feed else 44, bold=True), accent, line_gap=8, max_lines=3)
    y += 18
    draw.line([left, y, left + 95, y], fill=accent, width=5)
    y += 30
    body = 'Conteúdo estratégico, visual profissional e chamada clara para gerar interesse.'
    draw_wrapped(draw, body, (left, y), int(w * 0.46), font(25 if feed else 34), (52, 48, 45), line_gap=8, max_lines=2)

    btn_y = int(h * (0.76 if feed else 0.71))
    btn_w = 470
    draw.rounded_rectangle([left, btn_y, left + btn_w, btn_y + 86], radius=43, fill=accent, outline=blend(accent, (255,255,255), .45), width=3)
    draw.ellipse([left + 30, btn_y + 22, left + 72, btn_y + 64], outline=(255, 255, 255), width=3)
    draw.line([left + 41, btn_y + 43, left + 61, btn_y + 43], fill=(255,255,255), width=3)
    draw.text((left + 95, btn_y + 23), 'Agende sua avaliação' if post.objective != 'oferta' else 'Fale conosco', font=font(32, bold=True), fill=(255, 255, 255))

    footer_h = 150 if feed else 210
    footer_y = h - footer_h
    draw.rectangle([0, footer_y, w, h], fill=blend(cream, (255, 255, 255), .25))
    draw.arc([-80, footer_y-120, w+110, footer_y+115], 10, 178, fill=accent, width=8)
    monogram = ''.join([p[0] for p in brand.business_name.split()[:2]]).upper() or 'AI'
    draw.text((left, footer_y + 42), monogram, font=font(52, bold=True, serif=True), fill=accent)
    draw.line([left+94, footer_y + 35, left+94, footer_y + 105], fill=blend(accent, (255,255,255), .35), width=2)
    draw.text((left + 125, footer_y + 34), brand.business_name[:26], font=font(30 if feed else 38, serif=True), fill=dark)
    draw.text((left + 125, footer_y + 72), (brand.instagram or '@suamarca')[:30], font=font(23 if feed else 31), fill=(96, 88, 82))
    labels = [('AVALIAÇÃO', 'PERSONALIZADA'), ('ESTRATÉGIA', 'SEGURA'), ('RESULTADOS', 'NATURAIS')]
    x0 = int(w * 0.60)
    gap = 132
    for i, (a, b) in enumerate(labels):
        x = x0 + i * gap
        draw.ellipse([x, footer_y + 28, x+42, footer_y + 70], outline=accent, width=3)
        draw.text((x - 26, footer_y + 78), a, font=font(14 if feed else 20, bold=True), fill=(96, 88, 82))
        draw.text((x - 31, footer_y + 98), b, font=font(14 if feed else 20), fill=(96, 88, 82))
        if i < 2:
            draw.line([x + 90, footer_y + 34, x + 90, footer_y + 108], fill=blend(accent, (255,255,255), .50), width=2)

    # Leve nitidez para ficar menos “caseiro”.
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=105, threshold=3))
    filename = safe_filename(post.id)
    path = PRIVATE_DIR / filename
    img.save(path, 'PNG', optimize=True)
    return filename



def generate_ai_premium_image(post, brand, hero_img, body_text=None, cta_text=None):
    """Composição premium: IA cria a foto/fundo; o sistema aplica textos legíveis e marca."""
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    feed = post.format == 'feed'
    w, h = (1080, 1080) if feed else (1080, 1920)
    primary = hex_to_rgb(brand.primary_color, (55, 37, 26))
    secondary = hex_to_rgb(brand.secondary_color, (247, 239, 230))
    accent = hex_to_rgb(brand.accent_color, (184, 138, 68))
    dark = (34, 24, 18)
    cream = blend(secondary, (255, 255, 255), 0.55)

    if hero_img is None:
        return generate_image(post, brand)

    bg = fit_cover(hero_img, (w, h)).filter(ImageFilter.UnsharpMask(radius=1.0, percent=110, threshold=3))
    overlay = Image.new('RGBA', (w, h), (0,0,0,0))
    d = ImageDraw.Draw(overlay)

    # Véu premium para garantir leitura do texto.
    panel_w = int(w * (0.62 if feed else 0.82))
    d.rounded_rectangle([0, 0, panel_w, h], radius=0, fill=(*cream, 238))
    # Degradê suave do painel para a foto.
    for x in range(panel_w-180, panel_w+90):
        if 0 <= x < w:
            t = min(max((x - (panel_w-180)) / 270, 0), 1)
            alpha = int(238 * (1-t))
            d.line([(x, 0), (x, h)], fill=(*cream, alpha))
    # Curvas e detalhes de luxo.
    for i, r in enumerate([520, 760, 1040]):
        box = [w - r//2, 90+i*55, w + r//2, 90+i*55+r]
        d.ellipse(box, outline=(*blend(accent, (255,255,255), .60), 130), width=3)
    d.line([72, 122 if feed else 150, 500, 122 if feed else 150], fill=(*accent, 210), width=2)
    d.rounded_rectangle([54, h-170 if feed else h-235, w-54, h-38], radius=32, fill=(*blend(cream, (255,255,255), .20), 232))
    d.arc([-120, h-250 if feed else h-325, w+160, h-25], 10, 178, fill=(*accent, 230), width=8)

    img = Image.alpha_composite(bg.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)
    left = 76
    top = 78 if feed else 112
    draw_lotus(draw, left + 48, top + 20, accent)

    headline = (post.title or '').upper()
    title_size = 56 if feed else 72
    if len(headline) > 58:
        title_size -= 7
    y = top + 105
    max_text = int(w * (0.50 if feed else 0.72))
    y = draw_wrapped(draw, headline, (left, y), max_text, font(title_size, bold=True, serif=True), dark, line_gap=12, max_lines=4 if feed else 6)
    y += 20
    y = draw_wrapped(draw, (post.subtitle or '').upper(), (left, y), max_text, font(32 if feed else 44, bold=True), accent, line_gap=8, max_lines=3)
    y += 20
    draw.line([left, y, left + 100, y], fill=accent, width=5)
    y += 30
    body = body_text or 'Conteúdo estratégico, visual profissional e chamada clara para gerar interesse.'
    draw_wrapped(draw, body, (left, y), int(w * (0.46 if feed else 0.70)), font(24 if feed else 34), (52, 48, 45), line_gap=9, max_lines=3)

    btn_y = int(h * (0.74 if feed else 0.70))
    btn_w = 470 if feed else 610
    cta = cta_text or ('Fale conosco' if post.objective == 'oferta' else 'Agende sua avaliação')
    draw.rounded_rectangle([left, btn_y, left + btn_w, btn_y + 86], radius=43, fill=accent, outline=blend(accent, (255,255,255), .45), width=3)
    draw.ellipse([left + 30, btn_y + 22, left + 72, btn_y + 64], outline=(255, 255, 255), width=3)
    draw.line([left + 41, btn_y + 43, left + 61, btn_y + 43], fill=(255,255,255), width=3)
    draw.text((left + 95, btn_y + 23), cta[:34], font=font(30 if feed else 38, bold=True), fill=(255, 255, 255))

    footer_y = h - (150 if feed else 210)
    monogram = ''.join([part[0] for part in brand.business_name.split()[:2]]).upper() or 'AI'
    draw.text((left, footer_y + 42), monogram, font=font(52 if feed else 66, bold=True, serif=True), fill=accent)
    draw.line([left+94, footer_y + 35, left+94, footer_y + 105], fill=blend(accent, (255,255,255), .35), width=2)
    draw.text((left + 125, footer_y + 34), brand.business_name[:26], font=font(30 if feed else 42, serif=True), fill=dark)
    draw.text((left + 125, footer_y + 72), (brand.instagram or '@suamarca')[:30], font=font(23 if feed else 33), fill=(96, 88, 82))

    if feed:
        labels = [('IA', 'PREMIUM'), ('COPY', 'ESTRATÉGICA'), ('VISUAL', 'PROFISSIONAL')]
        x0 = int(w * 0.60)
        gap = 132
        for i, (a, b) in enumerate(labels):
            x = x0 + i * gap
            draw.ellipse([x, footer_y + 28, x+42, footer_y + 70], outline=accent, width=3)
            draw.text((x - 10, footer_y + 78), a, font=font(14, bold=True), fill=(96, 88, 82))
            draw.text((x - 29, footer_y + 98), b, font=font(14), fill=(96, 88, 82))
            if i < 2:
                draw.line([x + 90, footer_y + 34, x + 90, footer_y + 108], fill=blend(accent, (255,255,255), .50), width=2)

    filename = safe_filename(post.id)
    path = PRIVATE_DIR / filename
    img.save(path, 'PNG', optimize=True)
    return filename

def make_preview_image(path):
    img = Image.open(path).convert('RGB')
    max_w = 640
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)))
    overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
    d = ImageDraw.Draw(overlay)
    wm_font = font(max(24, img.width // 22), bold=True)
    text = 'PRÉVIA • DOWNLOAD LIBERADO COM CRÉDITOS'
    for y in range(35, img.height, 165):
        d.text((24, y), text, fill=(17, 24, 39, 72), font=wm_font)
    d.rounded_rectangle([18, 18, img.width-18, 72], radius=20, fill=(255,255,255,205))
    d.text((36, 35), 'Prévia com marca d’água', fill=(17,24,39,210), font=font(22, bold=True))
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    out = BytesIO()
    img.save(out, format='PNG')
    out.seek(0)
    return out


@app.route('/healthz')
def healthz():
    return jsonify({'ok': True, 'time': datetime.utcnow().isoformat()})


@app.route('/')
def home():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('home.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form.get('password', '')
        if len(password) < 6:
            flash('A senha precisa ter pelo menos 6 caracteres.', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Este e-mail já está cadastrado. Entre com sua senha ou use “Esqueci minha senha”.', 'error')
            return redirect(url_for('login'))
        user = User(
            name=request.form['name'].strip(),
            email=email,
            password_hash=generate_password_hash(password),
            auth_provider='email',
            credits=0,
        )
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        return redirect(url_for('brand'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email'].strip().lower()).first()
        if not user or not check_password_hash(user.password_hash, request.form['password']):
            flash('E-mail ou senha inválidos.', 'error')
            return redirect(url_for('login'))
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            link = create_password_reset_link(user)
            body = (
                f"Olá, {user.name}!\n\n"
                f"Recebemos uma solicitação para redefinir sua senha.\n"
                f"Acesse este link em até 2 horas:\n{link}\n\n"
                f"Se você não solicitou isso, ignore este e-mail."
            )
            sent = send_email_message(user.email, f'Redefinir senha - {get_setting("site_name", "SocialAI Pro")}', body)
            if not sent and app.config.get('ENABLE_FAKE_PAYMENT'):
                flash(f'Modo teste: link de redefinição gerado: {link}', 'success')
            else:
                flash('Se esse e-mail estiver cadastrado, enviamos um link para redefinir sua senha.', 'success')
        else:
            flash('Se esse e-mail estiver cadastrado, enviamos um link para redefinir sua senha.', 'success')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    reset = find_password_reset_token(token)
    if not reset:
        flash('Link inválido ou expirado. Solicite uma nova redefinição de senha.', 'error')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(password) < 6:
            flash('A senha precisa ter pelo menos 6 caracteres.', 'error')
            return redirect(request.url)
        if password != confirm:
            flash('As senhas não conferem.', 'error')
            return redirect(request.url)
        user = User.query.get_or_404(reset.user_id)
        user.password_hash = generate_password_hash(password)
        user.auth_provider = user.auth_provider or 'email'
        reset.used_at = datetime.utcnow()
        db.session.commit()
        flash('Senha redefinida. Agora você já pode entrar.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html')


@app.route('/auth/google')
def google_login():
    if not is_google_login_enabled():
        flash('Login com Google ainda não configurado pelo administrador.', 'error')
        return redirect(url_for('login'))
    redirect_uri = url_for('google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/auth/google/callback')
def google_callback():
    if not is_google_login_enabled():
        flash('Login com Google ainda não configurado.', 'error')
        return redirect(url_for('login'))
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo')
        if not userinfo:
            userinfo = oauth.google.get('https://openidconnect.googleapis.com/v1/userinfo').json()
    except Exception as exc:
        app.logger.exception('Erro no login Google: %s', exc)
        flash('Não foi possível entrar com Google. Tente novamente.', 'error')
        return redirect(url_for('login'))

    email = (userinfo.get('email') or '').lower().strip()
    google_id = userinfo.get('sub')
    name = userinfo.get('name') or email.split('@')[0]
    if not email or not google_id:
        flash('Não recebemos e-mail válido do Google.', 'error')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    if user:
        if not user.google_id:
            user.google_id = google_id
        user.auth_provider = 'google' if user.auth_provider == 'email' else user.auth_provider
    else:
        user = User(
            name=name,
            email=email,
            google_id=google_id,
            auth_provider='google',
            password_hash=generate_password_hash(secrets.token_urlsafe(32)),
            credits=0,
        )
        db.session.add(user)
    db.session.commit()
    session['user_id'] = user.id
    flash('Login com Google realizado com sucesso.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'profile':
            user.name = request.form.get('name', '').strip() or user.name
            db.session.commit()
            flash('Perfil atualizado.', 'success')
        elif action == 'password':
            current = request.form.get('current_password', '')
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            if not check_password_hash(user.password_hash, current):
                flash('Senha atual incorreta.', 'error')
            elif len(password) < 6:
                flash('A nova senha precisa ter pelo menos 6 caracteres.', 'error')
            elif password != confirm:
                flash('As senhas não conferem.', 'error')
            else:
                user.password_hash = generate_password_hash(password)
                db.session.commit()
                flash('Senha alterada.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/brand', methods=['GET', 'POST'])
@login_required
def brand():
    brand = get_brand()
    if request.method == 'POST':
        if not brand:
            brand = Brand(user_id=session['user_id'])
            db.session.add(brand)
        brand.business_name = request.form['business_name'].strip()
        brand.niche = request.form['niche'].strip()
        brand.audience = request.form['audience'].strip()
        brand.offer = request.form['offer'].strip()
        brand.tone = request.form['tone']
        brand.primary_color = request.form.get('primary_color') or '#1f2937'
        brand.secondary_color = request.form.get('secondary_color') or '#f7efe6'
        brand.accent_color = request.form.get('accent_color') or '#b88a44'
        brand.instagram = request.form.get('instagram') or '@suamarca'
        db.session.commit()
        flash('Marca salva com sucesso.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('brand.html', brand=brand)


@app.route('/dashboard')
@login_required
def dashboard():
    brand = get_brand()
    posts = Post.query.filter_by(user_id=session['user_id']).order_by(Post.created_at.desc()).limit(10).all()
    purchases = Purchase.query.filter_by(user_id=session['user_id']).order_by(Purchase.created_at.desc()).limit(5).all()
    return render_template('dashboard.html', user=current_user(), brand=brand, posts=posts, purchases=purchases)


@app.route('/generate', methods=['GET', 'POST'])
@login_required
def generate():
    brand = get_brand()
    if not brand:
        flash('Cadastre sua marca antes de gerar posts.', 'error')
        return redirect(url_for('brand'))
    if request.method == 'POST':
        topic = request.form['topic'].strip()
        qty = max(1, min(int(request.form.get('qty', 3)), app.config['FREE_PREVIEW_LIMIT']))
        format_name = request.form.get('format', 'feed')
        style = request.form.get('style', 'premium')
        objective = request.form.get('objective', 'interesse')
        generation_mode = request.form.get('generation_mode', 'template')
        premium_enabled = get_setting('premium_ai_enabled', '1') == '1'
        premium_cost = max(0, int(get_setting('ai_premium_cost', os.getenv('AI_PREMIUM_COST', '3')) or 0))
        user = current_user()
        use_premium_ai = generation_mode == 'premium_ai' and premium_enabled
        if use_premium_ai and not os.getenv('OPENAI_API_KEY'):
            flash('Modo IA Premium ainda não está configurado. Adicione OPENAI_API_KEY no Render e tente novamente.', 'error')
            return redirect(url_for('generate'))
        if use_premium_ai and user.credits < premium_cost * qty:
            flash(f'IA Premium exige {premium_cost} créditos por arte gerada. Você tem {user.credits} crédito(s).', 'error')
            return redirect(url_for('plans'))

        schedule_start = datetime.utcnow() + timedelta(days=1)
        generated_with_ai = 0
        for i in range(qty):
            ai_pack = ai_text_pack(brand, topic, objective, style) if use_premium_ai else None
            title = (ai_pack or {}).get('title') or strategic_title(topic, objective, brand)
            subtitle = (ai_pack or {}).get('subtitle') or make_subtitle(topic, objective, brand)
            post = Post(
                user_id=session['user_id'],
                title=title,
                subtitle=subtitle,
                caption=(ai_pack or {}).get('caption') or generate_caption(brand, topic, objective),
                hashtags=(ai_pack or {}).get('hashtags') or make_hashtags(brand, topic),
                format=format_name,
                style=style,
                objective=objective,
                status='scheduled' if request.form.get('auto_schedule') else 'draft',
                scheduled_at=schedule_start + timedelta(days=i*2) if request.form.get('auto_schedule') else None,
            )
            db.session.add(post)
            db.session.commit()
            if use_premium_ai:
                hero = create_ai_visual_asset(brand, topic, objective, style, format_name)
                if hero is not None:
                    post.image_file = generate_ai_premium_image(post, brand, hero, (ai_pack or {}).get('body'), (ai_pack or {}).get('cta'))
                    user.credits -= premium_cost
                    generated_with_ai += 1
                else:
                    post.image_file = generate_image(post, brand)
                    flash('A IA visual não respondeu em uma geração; usei o template premium como fallback sem cobrar os créditos dessa arte.', 'error')
            else:
                post.image_file = generate_image(post, brand)
            db.session.commit()
        if generated_with_ai:
            flash(f'{generated_with_ai} arte(s) com IA Premium gerada(s). Foram consumidos {premium_cost * generated_with_ai} créditos de geração. O download final ainda exige créditos.', 'success')
        else:
            flash(f'{qty} post(s) por template premium gerado(s). A prévia tem marca d’água; o PNG final exige créditos.', 'success')
        return redirect(url_for('posts'))
    return render_template('generate.html', brand=brand)


@app.route('/posts')
@login_required
def posts():
    all_posts = Post.query.filter_by(user_id=session['user_id']).order_by(Post.created_at.desc()).all()
    return render_template('posts.html', posts=all_posts)


@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.filter_by(id=post_id, user_id=session['user_id']).first_or_404()
    brand = get_brand()
    if request.method == 'POST':
        post.title = request.form['title'].strip()
        post.subtitle = request.form.get('subtitle', '').strip()
        post.caption = request.form['caption'].strip()
        post.hashtags = request.form.get('hashtags', '').strip()
        post.format = request.form.get('format', post.format)
        post.style = request.form.get('style', post.style)
        post.objective = request.form.get('objective', post.objective)
        post.status = request.form.get('status', post.status)
        sched = request.form.get('scheduled_at')
        post.scheduled_at = datetime.fromisoformat(sched) if sched else None
        post.image_file = generate_image(post, brand)
        db.session.commit()
        flash('Post atualizado e arte regenerada em padrão premium.', 'success')
        return redirect(url_for('edit_post', post_id=post.id))
    return render_template('edit_post.html', post=post)


@app.route('/calendar')
@login_required
def calendar():
    scheduled = Post.query.filter_by(user_id=session['user_id']).filter(Post.scheduled_at.isnot(None)).order_by(Post.scheduled_at.asc()).all()
    return render_template('calendar.html', posts=scheduled)


@app.route('/preview/<int:post_id>')
@login_required
def preview(post_id):
    post = Post.query.filter_by(id=post_id, user_id=session['user_id']).first_or_404()
    if not post.image_file:
        abort(404)
    path = PRIVATE_DIR / post.image_file
    if not path.exists():
        abort(404)
    return send_file(make_preview_image(path), mimetype='image/png')


@app.route('/download/<int:post_id>')
@login_required
def download(post_id):
    user = current_user()
    post = Post.query.filter_by(id=post_id, user_id=user.id).first_or_404()
    if not post.image_file:
        abort(404)
    if user.credits <= 0:
        flash('Você precisa comprar créditos antes de baixar o PNG final sem marca d’água.', 'error')
        return redirect(url_for('plans'))
    path = PRIVATE_DIR / post.image_file
    if not path.exists():
        abort(404)
    user.credits -= 1
    db.session.add(DownloadLog(user_id=user.id, post_id=post.id, filename=post.image_file))
    db.session.commit()
    return send_from_directory(str(PRIVATE_DIR), post.image_file, as_attachment=True)


@app.route('/plans')
@login_required
def plans():
    purchases = Purchase.query.filter_by(user_id=session['user_id']).order_by(Purchase.created_at.desc()).limit(10).all()
    plans = active_plans()
    packages = [p for p in plans if p.plan_type == 'package']
    subscriptions = [p for p in plans if p.plan_type == 'subscription']
    return render_template('plans.html', packages=packages, subscriptions=subscriptions, purchases=purchases, pix_key=get_setting('pix_key', app.config['PIX_KEY']))


@app.route('/purchase/<package_key>', methods=['POST'])
@login_required
def purchase(package_key):
    plan = CommercialPlan.query.filter_by(key=package_key, active=True).first_or_404()
    order = Purchase(user_id=session['user_id'], package_key=package_key, package_name=plan.name, credits=plan.total_credits, amount_cents=plan.amount_cents, status='pending')
    db.session.add(order)
    db.session.commit()
    return redirect(url_for('pay', purchase_id=order.id))


@app.route('/pay/<int:purchase_id>', methods=['GET', 'POST'])
@login_required
def pay(purchase_id):
    order = Purchase.query.filter_by(id=purchase_id, user_id=session['user_id']).first_or_404()
    if request.method == 'POST':
        order.proof_text = request.form.get('proof_text', '').strip()[:255]
        db.session.commit()
        flash('Comprovante/anotação enviado. Aguarde a aprovação do administrador.', 'success')
        return redirect(url_for('plans'))
    return render_template('pay.html', order=order, pix_key=get_setting('pix_key', app.config['PIX_KEY']), fake_enabled=app.config['ENABLE_FAKE_PAYMENT'])


@app.route('/fake-paid/<int:purchase_id>', methods=['POST'])
@login_required
def fake_paid(purchase_id):
    if not app.config['ENABLE_FAKE_PAYMENT']:
        abort(404)
    order = Purchase.query.filter_by(id=purchase_id, user_id=session['user_id']).first_or_404()
    if order.status != 'paid':
        user = current_user()
        order.status = 'paid'
        order.paid_at = datetime.utcnow()
        user.credits += order.credits
        db.session.commit()
    flash('Pagamento simulado aprovado. Créditos adicionados.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    orders = Purchase.query.order_by(Purchase.created_at.desc()).all()
    users = {u.id: u for u in User.query.all()}
    return render_template('admin_orders.html', orders=orders, users=users)


@app.route('/admin/orders/<int:purchase_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_order(purchase_id):
    order = Purchase.query.get_or_404(purchase_id)
    user = User.query.get(order.user_id)
    if order.status != 'paid':
        order.status = 'paid'
        order.paid_at = datetime.utcnow()
        user.credits += order.credits
        db.session.commit()
        flash('Pedido aprovado e créditos adicionados.', 'success')
    return redirect(url_for('admin_orders'))


@app.route('/admin/orders/<int:purchase_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_order(purchase_id):
    order = Purchase.query.get_or_404(purchase_id)
    if order.status == 'pending':
        order.status = 'cancelled'
        db.session.commit()
        flash('Pedido cancelado.', 'success')
    return redirect(url_for('admin_orders'))


@app.route('/admin/commercial')
@login_required
@admin_required
def admin_commercial():
    plans = CommercialPlan.query.order_by(CommercialPlan.sort_order.asc(), CommercialPlan.id.asc()).all()
    settings = {k: get_setting(k, v) for k, v in DEFAULT_SETTINGS.items()}
    stats = {
        'users': User.query.count(),
        'pending': Purchase.query.filter_by(status='pending').count(),
        'paid': Purchase.query.filter_by(status='paid').count(),
        'revenue_cents': sum(o.amount_cents for o in Purchase.query.filter_by(status='paid').all()),
    }
    return render_template('admin_commercial.html', plans=plans, settings=settings, stats=stats)


@app.route('/admin/commercial/settings', methods=['POST'])
@login_required
@admin_required
def admin_save_settings():
    for key in DEFAULT_SETTINGS.keys():
        set_setting(key, request.form.get(key, '').strip())
    db.session.commit()
    flash('Configurações comerciais salvas.', 'success')
    return redirect(url_for('admin_commercial'))


@app.route('/admin/commercial/plans/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_plan():
    plan = CommercialPlan(active=True, plan_type='package', sort_order=99, amount_cents=0, credits=0, bonus_credits=0)
    if request.method == 'POST':
        return save_plan_from_form(plan, is_new=True)
    return render_template('admin_plan_form.html', plan=plan, action='Criar plano')


@app.route('/admin/commercial/plans/<int:plan_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_plan(plan_id):
    plan = CommercialPlan.query.get_or_404(plan_id)
    if request.method == 'POST':
        return save_plan_from_form(plan, is_new=False)
    return render_template('admin_plan_form.html', plan=plan, action='Salvar alterações')


def save_plan_from_form(plan, is_new=False):
    key = request.form['key'].strip().lower().replace(' ', '_')
    key = re.sub(r'[^a-z0-9_\-]', '', key)
    if not key:
        flash('Informe uma chave válida para o plano.', 'error')
        return redirect(request.url)
    existing = CommercialPlan.query.filter_by(key=key).first()
    if existing and existing.id != plan.id:
        flash('Já existe um plano com essa chave.', 'error')
        return redirect(request.url)
    plan.key = key
    plan.name = request.form['name'].strip()
    plan.plan_type = request.form.get('plan_type', 'package')
    plan.credits = max(0, int(request.form.get('credits') or 0))
    plan.bonus_credits = max(0, int(request.form.get('bonus_credits') or 0))
    plan.amount_cents = parse_money_to_cents(request.form.get('amount'))
    original = request.form.get('original_amount', '').strip()
    plan.original_amount_cents = parse_money_to_cents(original) if original else None
    plan.description = request.form.get('description', '').strip()
    plan.badge = request.form.get('badge', '').strip() or None
    plan.cta = request.form.get('cta', '').strip() or 'Comprar'
    plan.featured = request.form.get('featured') == 'on'
    plan.active = request.form.get('active') == 'on'
    plan.sort_order = int(request.form.get('sort_order') or 0)
    if is_new:
        db.session.add(plan)
    db.session.commit()
    flash('Plano salvo no painel comercial.', 'success')
    return redirect(url_for('admin_commercial'))


@app.route('/admin/commercial/plans/<int:plan_id>/toggle', methods=['POST'])
@login_required
@admin_required
def admin_toggle_plan(plan_id):
    plan = CommercialPlan.query.get_or_404(plan_id)
    plan.active = not plan.active
    db.session.commit()
    flash('Status do plano alterado.', 'success')
    return redirect(url_for('admin_commercial'))


@app.cli.command('init-db')
def init_db():
    INSTANCE_DIR.mkdir(exist_ok=True)
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    db.create_all()
    ensure_schema_updates()
    seed_commercial_defaults()
    print('Banco criado/atualizado e painel comercial configurado.')


with app.app_context():
    INSTANCE_DIR.mkdir(exist_ok=True)
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    db.create_all()
    ensure_schema_updates()
    seed_commercial_defaults()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=os.getenv('FLASK_DEBUG') == '1')
