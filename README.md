# SocialAI SaaS — Versão Premium com OpenAI

Sistema Flask pronto para Render com:

- Login/cadastro
- Cadastro de marca
- Posts por template premium
- Posts com IA Visual Premium via OpenAI
- Legenda, hashtags e CTA gerados por IA
- Preview com marca d'água
- Download final bloqueado por créditos
- Painel comercial para planos, promoções, PIX e IA Premium
- Painel admin para aprovar pagamentos manuais

## Variáveis obrigatórias no Render

```env
SECRET_KEY=uma-chave-grande-e-secreta
ADMIN_EMAIL=seuemail@gmail.com
PIX_KEY=sua-chave-pix
ENABLE_FAKE_PAYMENT=0
UPLOAD_FOLDER=/tmp/generated_private
FREE_PREVIEW_LIMIT=30
OPENAI_API_KEY=sua-chave-da-openai
OPENAI_TEXT_MODEL=gpt-4.1-mini
OPENAI_IMAGE_MODEL=gpt-image-1
AI_PREMIUM_COST=3
```

Para produção com banco persistente, configure também:

```env
DATABASE_URL=postgresql://...
```

## Comandos Render

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
gunicorn app:app
```

## Como funciona a IA Premium

1. Cliente escolhe modo `IA Visual Premium`.
2. O sistema exige créditos antes de chamar a API.
3. A IA gera a copy estratégica.
4. A IA gera uma imagem sem texto.
5. O sistema aplica headline, CTA e marca por cima para manter o texto legível.
6. A prévia aparece com marca d'água.
7. O download final consome crédito normalmente.

## Observação de custo

O modo IA Premium usa API paga. Por padrão, cada arte gerada consome 3 créditos do usuário, além do crédito de download final. Você pode alterar isso no Painel Comercial.
