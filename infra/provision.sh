#!/usr/bin/env bash
# =============================================================================
# Velmo 2.0 — provisioning Azure (phase 0). À lancer UNE FOIS.
#
# COMMENT LANCER (dans Azure Cloud Shell — le terminal du portail, déjà connecté,
# OU en local après `az login`) :
#   1. Édite la ligne PGPASS ci-dessous (mets un vrai mot de passe).
#   2. Lance :  bash infra/provision.sh
#
# Déjà fait de ton côté : la Container App velmo2-tony (2 Gio), l'environnement
# Velmo2Tony, le compte de stockage storagetonylucas.
# Content Safety : RIEN à créer — on réutilise AZURE_CONTENT_SAFETY_* de ton .env.
# Déploiement : MANUEL sur cet abonnement (l'attribution de rôle est interdite,
# donc pas de service principal ni de CI auto-deploy — voir le récap final).
# =============================================================================
set -euo pipefail

# ============================ À ÉDITER ============================
PGPASS="change-me-strong-password"   # mot de passe de la base Postgres (note-le !)
# =================================================================

# --- Nos noms de ressources (ne pas changer) ---
RG=tlucasRG            # Resource Group = le "dossier" qui regroupe nos ressources
ENV=Velmo2Tony        # environnement Container Apps = le "réseau privé" commun
LOC=swedencentral     # région Azure (datacenter)
STG=storagetonylucas  # compte de stockage (créé ; volume Chroma optionnel, cf. étape 3)

echo "==> 1/3  Disque persistant (Azure Files) — pour un usage optionnel plus tard"
# Crée un dossier persistant 'chromadata' et le déclare à l'environnement sous le nom
# 'chromastore'. Il n'est PAS branché automatiquement (le montage via CLI échoue sur cet
# abonnement) ; tu pourras le brancher via le portail plus tard si tu veux la persistance.
KEY=$(az storage account keys list -g "$RG" -n "$STG" --query "[0].value" -o tsv)
az storage share-rm create -g "$RG" --storage-account "$STG" -n chromadata --quota 8 -o none
az containerapp env storage set -g "$RG" -n "$ENV" --storage-name chromastore \
  --azure-file-account-name "$STG" --azure-file-account-key "$KEY" \
  --azure-file-share-name chromadata --access-mode ReadWrite -o none

echo "==> 2/3  Postgres (conteneur, éphémère, réseau interne uniquement)"
# Base relationnelle dans un conteneur (la version managée est bloquée sur l'abonnement).
# Pas de disque : les données sont recréées au démarrage par le seed (déterministes).
if ! az containerapp show -g "$RG" -n velmo2-tony-pg -o none 2>/dev/null; then
  az containerapp create -g "$RG" -n velmo2-tony-pg --environment "$ENV" \
    --image postgres:16-alpine --transport tcp --ingress internal \
    --target-port 5432 --exposed-port 5432 --min-replicas 1 --max-replicas 1 \
    --cpu 0.5 --memory 1.0Gi --secrets "pgpass=$PGPASS" \
    --env-vars POSTGRES_USER=app POSTGRES_PASSWORD=secretref:pgpass POSTGRES_DB=velmo -o none
fi

echo "==> 3/3  Chroma (conteneur, éphémère)"
# Base vectorielle dans un conteneur. Éphémère (pas de volume) : monter un volume Azure
# Files via CLI échoue sur cet abonnement (bug de l'option --yaml). Les faits durables
# persistent le temps d'une session (minReplicas=1), réinitialisés à un redéploiement.
# PERSISTANCE OPTIONNELLE plus tard, via le portail : Container App velmo2-tony-chroma
# -> Volumes -> Azure Files 'chromastore', point de montage /chroma/chroma.
if ! az containerapp show -g "$RG" -n velmo2-tony-chroma -o none 2>/dev/null; then
  az containerapp create -g "$RG" -n velmo2-tony-chroma --environment "$ENV" \
    --image chromadb/chroma:0.5.23 --transport tcp --ingress internal \
    --target-port 8000 --exposed-port 8000 --min-replicas 1 --max-replicas 1 \
    --cpu 0.5 --memory 1.0Gi -o none
fi

# --- Récapitulatif des valeurs à réutiliser ---
DOMAIN=$(az containerapp env show -g "$RG" -n "$ENV" --query properties.defaultDomain -o tsv)
cat <<EOF

===================== PROVISIONING TERMINÉ =====================
Domaine interne de l'environnement : $DOMAIN

À utiliser comme config de l'app (au déploiement) :
  DB_URL     = postgresql+psycopg://app:$PGPASS@velmo2-tony-pg.internal.$DOMAIN:5432/velmo
  CHROMA_URL = http://velmo2-tony-chroma.internal.$DOMAIN:8000

Content Safety + Kimi : réutilise AZURE_CONTENT_SAFETY_* et AZURE_AI_INFERENCE_* de ton .env.

DÉPLOIEMENT (manuel — attribution de rôle interdite sur cet abonnement, donc pas de
CI auto-deploy). Une fois le code prêt (Dockerfile Streamlit), lance depuis ta session az :
  az containerapp up --source . --name velmo2-tony --resource-group $RG
================================================================
EOF
