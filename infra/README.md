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

# 1. Config de l'app (une fois ; env + secrets sont portés d'une révision à l'autre).
az containerapp update -g tlucasRG -n velmo2-tony \
  --secrets azkey=<kimi-key> pgpass=<pgpass> safetykey=<safety-key> \
  --set-env-vars \
    DB_URL="postgresql+psycopg://app:<pgpass>@velmo2-tony-pg.internal.<domain>:5432/velmo" \
    CHROMA_URL="http://velmo2-tony-chroma.internal.<domain>:8000" \
    AZURE_AI_INFERENCE_ENDPOINT="<kimi-endpoint>" \
    AZURE_AI_INFERENCE_MODEL="Kimi-K2.6" \
    AZURE_AI_INFERENCE_API_KEY=secretref:azkey \
    AZURE_CONTENT_SAFETY_ENDPOINT="<safety-endpoint>" \
    AZURE_CONTENT_SAFETY_KEY=secretref:safetykey \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# 2. Build + push + déploiement (crée un ACR au premier appel).
az containerapp up --source . --name velmo2-tony --resource-group tlucasRG
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
