# SocialAI SaaS Premium com IA, Painel Comercial e Login Google

Versão pronta para Render com:

- Login/cadastro por e-mail e senha
- Esqueci minha senha
- Redefinição de senha por link
- Perfil do usuário e troca de senha
- Login/cadastro com Google OAuth opcional
- Painel comercial
- Créditos, pacotes e assinaturas manuais
- Modo Template Premium
- Modo IA Visual Premium via OpenAI API
- Preview com marca d'água e download final protegido por créditos

## Variáveis obrigatórias no Render

```env
SECRET_KEY=uma-chave-grande-e-secreta
ADMIN_EMAIL=seuemail@gmail.com
PIX_KEY=sua-chave-pix
ENABLE_FAKE_PAYMENT=0
UPLOAD_FOLDER=/tmp/generated_private
FREE_PREVIEW_LIMIT=30
DATABASE_URL=sua-url-postgresql
OPENAI_API_KEY=sua-chave-openai
OPENAI_TEXT_MODEL=gpt-4.1-mini
OPENAI_IMAGE_MODEL=gpt-image-1
AI_PREMIUM_COST=3
```

## Esqueci minha senha

Para enviar e-mail real, configure SMTP no Render:

```env
SMTP_HOST=smtp.seuprovedor.com
SMTP_PORT=587
SMTP_USER=seuemail@seudominio.com
SMTP_PASSWORD=sua-senha-ou-app-password
SMTP_FROM=seuemail@seudominio.com
SMTP_USE_TLS=1
```

Se SMTP não estiver configurado, o sistema não envia o e-mail. Em modo teste (`ENABLE_FAKE_PAYMENT=1`), ele mostra o link na tela para facilitar testes.

## Login com Google

Para ativar o botão de Google, configure no Render:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

No Google Cloud Console, crie um OAuth Client do tipo Web Application e adicione a URL autorizada de callback:

```text
https://SEU-SITE.onrender.com/auth/google/callback
```

Depois salve as variáveis no Render e faça redeploy.

## Deploy no Render

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
gunicorn app:app
```

## Atualizar site já publicado

1. Extraia o ZIP.
2. Envie todos os arquivos e pastas para o mesmo repositório GitHub.
3. Clique em Commit changes.
4. No Render, faça Manual Deploy > Deploy latest commit.

O sistema executa uma pequena atualização automática de banco para adicionar Google Login e recuperação de senha em bancos já existentes.
