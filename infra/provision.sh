#!/usr/bin/env bash
# =============================================================================
# Velmo 2.0 — provisioning Azure (phase 0). À lancer UNE FOIS.
#
# COMMENT LANCER (dans Azure Cloud Shell — le terminal du portail, déjà connecté) :
#   1. Ouvre https://portal.azure.com → icône terminal (Cloud Shell) → Bash.
#   2. Copie ce fichier dans Cloud Shell (ou clone le repo).
#   3. Édite la ligne PGPASS ci-dessous (mets un vrai mot de passe).
#   4. Lance :  bash infra/provision.sh
#
# Déjà fait de ton côté : la Container App velmo2-tony (2 Gio), l'environnement
# Velmo2Tony, le compte de stockage storagetonylucas.
# Content Safety : RIEN à créer — on réutilise AZURE_CONTENT_SAFETY_* de ton .env.
# =============================================================================
set -euo pipefail

# ============================ À ÉDITER ============================
PGPASS="change-me-strong-password"   # mot de passe de la base Postgres (note-le !)
# =================================================================

# --- Nos noms de ressources (ne pas changer) ---
RG=tlucasRG            # Resource Group = le "dossier" qui regroupe nos ressources
ENV=Velmo2Tony        # environnement Container Apps = le "réseau privé" commun
LOC=swedencentral     # région Azure (datacenter)
STG=storagetonylucas  # compte de stockage = le "disque dur externe" persistant

echo "==> 1/4  Disque persistant de Chroma (Azure Files)"
# Récupère la clé d'accès du disque, crée un dossier persistant 'chromadata' (8 Go),
# et le déclare à l'environnement sous le nom 'chromastore' pour pouvoir le brancher.
KEY=$(az storage account keys list -g "$RG" -n "$STG" --query "[0].value" -o tsv)
az storage share-rm create -g "$RG" --storage-account "$STG" -n chromadata --quota 8 -o none
az containerapp env storage set -g "$RG" -n "$ENV" --storage-name chromastore \
  --azure-file-account-name "$STG" --azure-file-account-key "$KEY" \
  --azure-file-share-name chromadata --access-mode ReadWrite -o none

echo "==> 2/4  Postgres (conteneur, éphémère, réseau interne uniquement)"
# Base relationnelle dans un conteneur (la version managée est bloquée sur l'abonnement).
# Pas de disque : les données sont recréées au démarrage par le seed (déterministes).
# Idempotent : on ne recrée pas si l'app existe déjà.
if ! az containerapp show -g "$RG" -n velmo2-tony-pg -o none 2>/dev/null; then
  az containerapp create -g "$RG" -n velmo2-tony-pg --environment "$ENV" \
    --image postgres:16-alpine --transport tcp --ingress internal \
    --target-port 5432 --exposed-port 5432 --min-replicas 1 --max-replicas 1 \
    --cpu 0.5 --memory 1.0Gi --secrets "pgpass=$PGPASS" \
    --env-vars POSTGRES_USER=app POSTGRES_PASSWORD=secretref:pgpass POSTGRES_DB=velmo -o none
fi

echo "==> 3/4  Chroma (conteneur, avec le disque persistant branché)"
# Chroma a besoin d'un volume monté ; ça passe par un fichier YAML au format "ressource
# complète" (location/name/type + properties). Ingress TCP :8000 (comme Postgres) pour
# que CHROMA_URL=http://...:8000 reste cohérent (en HTTP interne, ACA remapperait sur :80).
ENV_ID=$(az containerapp env show -g "$RG" -n "$ENV" --query id -o tsv)
TMP=$(mktemp)
cat > "$TMP" <<YAML
location: $LOC
name: velmo2-tony-chroma
type: Microsoft.App/containerApps
properties:
  managedEnvironmentId: $ENV_ID
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: false
      transport: Tcp
      targetPort: 8000
      exposedPort: 8000
  template:
    containers:
      - image: chromadb/chroma:0.5.23
        name: chroma
        resources:
          cpu: 0.5
          memory: "1.0Gi"
        volumeMounts:
          - volumeName: chromadata
            mountPath: /chroma/chroma
    scale:
      minReplicas: 1
      maxReplicas: 1
    volumes:
      - name: chromadata
        storageType: AzureFile
        storageName: chromastore
YAML
if ! az containerapp show -g "$RG" -n velmo2-tony-chroma -o none 2>/dev/null; then
  az containerapp create -g "$RG" -n velmo2-tony-chroma --yaml "$TMP" -o none
fi
rm -f "$TMP"

echo "==> 4/4  Compte robot pour que GitHub déploie tout seul (service principal)"
# Crée une identité machine avec droit de modifier les ressources du groupe.
SUB=$(az account show --query id -o tsv)
echo "----- Copie ce JSON dans le secret GitHub 'AZURE_CREDENTIALS' -----"
az ad sp create-for-rbac --name velmo2-deployer --role contributor \
  --scopes "/subscriptions/$SUB/resourceGroups/$RG" --sdk-auth

# --- Récapitulatif des valeurs à réutiliser ---
DOMAIN=$(az containerapp env show -g "$RG" -n "$ENV" --query properties.defaultDomain -o tsv)
cat <<EOF

===================== PROVISIONING TERMINÉ =====================
Domaine interne de l'environnement : $DOMAIN

À mettre dans la config de l'app (phase 2) :
  DB_URL     = postgresql+psycopg://app:$PGPASS@velmo2-tony-pg.internal.$DOMAIN:5432/velmo
  CHROMA_URL = http://velmo2-tony-chroma.internal.$DOMAIN:8000

Content Safety + Kimi : réutilise AZURE_CONTENT_SAFETY_* et AZURE_AI_INFERENCE_*
de ton .env (rien à créer).

Secrets GitHub à créer : AZURE_CREDENTIALS (le JSON ci-dessus), ACR_NAME (après le
premier build), et les clés Azure (voir infra/README.md, généré au chantier).
================================================================
EOF
