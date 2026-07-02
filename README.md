# SocialAI SaaS — versão com Painel Comercial

Sistema Flask pronto para rodar como site/SaaS de geração de posts com prévia protegida, créditos, venda por pacotes e painel comercial administrativo.

## O que está incluído

- Cadastro e login de usuários.
- Perfil de marca por usuário.
- Geração de posts com título, subtítulo, legenda, hashtags e arte PNG.
- Prévia com marca d’água.
- Arquivo final salvo em pasta privada.
- Download final apenas com créditos.
- Cada download consome 1 crédito.
- Pacotes avulsos de créditos.
- Planos mensais simulados por PIX/manual.
- Painel de pedidos para aprovar pagamentos.
- Painel comercial para editar preços, créditos, bônus, promoções, plano em destaque, textos de venda, nome do site, chave PIX e WhatsApp.
- Pronto para SQLite local e PostgreSQL online.
- Arquivos de deploy: Procfile, Dockerfile, render.yaml, runtime.txt.

## Painel comercial

Acesse com o usuário administrador em:

```text
/admin/commercial
```

O administrador consegue alterar sem mexer no código:

- Nome do site.
- Título e subtítulo da página inicial.
- Banner promocional da página de planos.
- Chave PIX.
- WhatsApp comercial.
- Criar novos planos.
- Editar planos existentes.
- Ativar/desativar planos.
- Definir tipo: pacote avulso ou assinatura mensal.
- Definir preço atual e preço original.
- Definir créditos e créditos bônus.
- Definir selo, como “Mais vendido”.
- Definir texto do botão.
- Destacar plano principal.
- Reordenar os planos na página.

## Planos padrão já cadastrados

- Teste — 5 créditos — R$ 19,90.
- Start Mensal — 30 + 10 bônus — R$ 49,90/mês.
- Pro Lançamento — 80 + 30 bônus — R$ 69,90/mês, com preço original R$ 99,90.
- Premium Mensal — 200 + 100 bônus — R$ 199,90/mês.
- Agência Avulso — 100 créditos — R$ 179,90.

Esses valores podem ser alterados pelo painel comercial.

## Como rodar localmente

```bash
cd socialai_saas_ready
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

No Windows:

```bash
cd socialai_saas_ready
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abra:

```text
http://127.0.0.1:5000
```

## Criar administrador

Configure o e-mail do administrador:

```bash
ADMIN_EMAIL=seuemail@seudominio.com
```

Depois crie uma conta no site usando esse mesmo e-mail. Esse usuário verá os menus **Pedidos** e **Comercial**.

## Variáveis de ambiente recomendadas

```bash
SECRET_KEY=uma-chave-grande-e-secreta
ADMIN_EMAIL=seuemail@seudominio.com
PIX_KEY=sua-chave-pix
ENABLE_FAKE_PAYMENT=0
DATABASE_URL=postgresql://usuario:senha@host:5432/banco
UPLOAD_FOLDER=/var/data/generated_private
FREE_PREVIEW_LIMIT=30
```

## Deploy no Render

1. Envie a pasta para um repositório GitHub.
2. Crie um PostgreSQL no Render.
3. Crie um Web Service apontando para o repositório.
4. Configure as variáveis de ambiente acima.
5. Use o comando de start:

```bash
gunicorn app:app
```

O arquivo `render.yaml` já ajuda na configuração.

## Observações importantes

- A assinatura mensal nesta versão funciona como venda manual por PIX: o cliente escolhe o plano, paga e o administrador aprova. Para cobrança automática recorrente, integre Asaas, Mercado Pago, Stripe ou Pagar.me com webhooks.
- A geração visual usa templates premium programáticos em PIL. Para resultados com fotos humanas realistas como campanhas de clínica, integre futuramente uma API de imagem ou banco de imagens.
- O sistema não faz postagem automática em Instagram/Facebook/LinkedIn, conforme solicitado.
