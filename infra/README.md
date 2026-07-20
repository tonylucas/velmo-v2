# Déploiement Velmo sur Azure Container Apps

Runbook opérationnel du chantier 005b. Trois parties : provisionner l'infra (une fois),
déployer l'app, et le rollback. Le **cœur CI** (gate d'éval + release) est indépendant
d'Azure et fonctionne sans rien de ce qui suit.

## Phase 0 — provisionner l'infra (une fois)

Prérequis créés à la main dans le portail : la Container App `velmo2-tony` (2 Gio), son
environnement `Velmo2Tony`, le compte de stockage `storagetonylucas` — le tout dans le
resource group `tlucasRG`, région `swedencentral`.

Ensuite, dans **Azure Cloud Shell** (ou en local après `az login`), édite le mot de passe
Postgres en haut de [`infra/provision.sh`](provision.sh) puis lance :

```bash
bash infra/provision.sh
```

Le script crée le partage Azure Files, la Container App **Postgres** (éphémère, interne) et
la Container App **Chroma** (éphémère, interne), puis affiche les valeurs `DB_URL` et
`CHROMA_URL` à réutiliser au déploiement.

> **Déploiement manuel sur cet abonnement.** Le compte de formation interdit l'attribution
> de rôles → pas de service principal → **pas de déploiement automatique par la CI**. Le
> fichier [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) reste livré pour
> un abonnement non bridé, mais ici on déploie à la main (ci-dessous).

## Déploiement (manuel)

Une fois l'infra en place et le code prêt (image Docker Streamlit du chantier), configure
les variables d'environnement de l'app, puis déploie — depuis ta session `az` :

```bash
# <domain> = az containerapp env show -g tlucasRG -n Velmo2Tony --query properties.defaultDomain -o tsv

# 1a. Poser les secrets (sensibles). `secret set`, PAS `update --secrets`.
#     DB_URL est mis en secret car il contient le mot de passe Postgres.
az containerapp secret set -g tlucasRG -n velmo2-tony --secrets \
  dburl="postgresql+psycopg://app:<pgpass>@velmo2-tony-pg.internal.<domain>:5432/velmo" \
  azkey=<kimi-key> \
  safetykey=<safety-key>

# 1b. Poser les variables d'env (les sensibles pointent vers les secrets ci-dessus).
#     env + secrets sont portés d'une révision à l'autre.
az containerapp update -g tlucasRG -n velmo2-tony --set-env-vars \
  DB_URL=secretref:dburl \
  CHROMA_URL="http://velmo2-tony-chroma.internal.<domain>:8000" \
  AZURE_AI_INFERENCE_ENDPOINT="<kimi-endpoint>" \
  AZURE_AI_INFERENCE_MODEL="Kimi-K2.6" \
  AZURE_AI_INFERENCE_API_KEY=secretref:azkey \
  AZURE_CONTENT_SAFETY_ENDPOINT="<safety-endpoint>" \
  AZURE_CONTENT_SAFETY_KEY=secretref:safetykey \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# 2. Build + push + déploiement (crée un ACR au premier appel).
az containerapp up --source . --name velmo2-tony --resource-group tlucasRG \
  --target-port 8000 --ingress external
```

Le build télécharge le modèle d'embedding depuis HuggingFace (il faut que HF soit joignable
**à ce moment-là**) ; le runtime, lui, est ensuite hors-ligne (`HF_HUB_OFFLINE=1`).

Content Safety et Kimi réutilisent la ressource Azure AI existante (`AZURE_CONTENT_SAFETY_*`
et `AZURE_AI_INFERENCE_*` de ton `.env`) — rien à créer.

## Rollback

Lister les révisions et réactiver la précédente — instantané, sans rebuild :

```bash
az containerapp revision list -g tlucasRG -n velmo2-tony -o table
az containerapp revision set-active -g tlucasRG -n velmo2-tony --revision <révision-précédente>
```

## Cœur CI (indépendant d'Azure)

- **Sur une PR** : poser le label `ready-for-eval` déclenche le gate d'éval offline
  ([`eval.yml`](../.github/workflows/eval.yml)). Un nouveau commit retire le label (il faut
  le reposer pour rejouer l'éval sur le code à jour). Rendre ce check **obligatoire** dans
  la *branch protection* de `main`.
- **Sur un tag `v*.*.*`** : [`release.yml`](../.github/workflows/release.yml) rejoue le gate
  et publie une **GitHub Release** portant les scores versionnés (`mlops/report.md` en asset).

## Observabilité (Langfuse)

Le traçage est **désactivé par défaut** : sans clés, l'agent tourne à l'identique.
Pour l'activer :

1. Créer un compte et un projet sur [cloud.langfuse.com](https://cloud.langfuse.com)
   (offre gratuite), puis copier les deux clés du projet.
2. Les poser sur la Container App — la clé secrète est un **secret**, pas une variable :

```bash
az containerapp secret set -g tlucasRG -n velmo2-tony --secrets lfsecret=<sk-lf-...>

az containerapp update -g tlucasRG -n velmo2-tony --set-env-vars \
  LANGFUSE_PUBLIC_KEY=<pk-lf-...> \
  LANGFUSE_SECRET_KEY=secretref:lfsecret \
  LANGFUSE_HOST=https://cloud.langfuse.com
```

Ce qui apparaît alors dans le dashboard, par tour : la latence, le coût (tokens
Kimi), la catégorie de garde-fou déclenchée, l'escalade et les erreurs d'outils.
Les tours d'un même client sont regroupés en conversation (`session_id`).

Ce qui **n'est pas** envoyé : le message brut. Seule la version masquée par
`check_input` part, et un message bloqué en entrée n'envoie aucun contenu — juste
son verdict, pour que le taux de blocage reste mesurable.

Le gate d'éval en CI reste **hors-ligne** et n'interroge jamais Langfuse : la note
bloquante doit rester déterministe et sans dépendance réseau.
