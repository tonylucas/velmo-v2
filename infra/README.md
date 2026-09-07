# Déploiement Velmo sur Azure

Runbook opérationnel. La conception (choix de services, secrets, plan mémoire, schéma
cible) est dans [`docs/dossier-deploiement-azure.md`](../docs/dossier-deploiement-azure.md) — ce fichier
ne couvre que l'exploitation. Le **cœur CI** (gate d'éval + release) est indépendant
d'Azure et fonctionne sans rien de ce qui suit.

> **Les noms de ressources sont des placeholders.** `<resource-group>`, `<app-name>`,
> `<pg-server>`, `<storage-account>`, `<acr-name>` remplacent les identifiants réels de
> l'abonnement, qui n'ont pas leur place dans un dépôt public. Les régions, versions
> d'image, dimensionnements et noms de variables, eux, sont ceux réellement utilisés.

## La topologie en une phrase

**Une seule App Service** (Web App for Containers, Linux, plan B1) qui fait tourner **deux
conteneurs** : le conteneur principal Velmo (notre image, construite dans l'ACR, Streamlit
sur le port 8000) et un **conteneur secondaire Chroma** (image officielle
`chromadb/chroma:0.5.23`, joint en `http://localhost:8001`) dont le dossier de données est
monté sur **Azure Files** — c'est ce volume qui rend la mémoire long terme persistante et
partagée entre postes. Le reste est managé : **PostgreSQL Flexible Server** pour les données
métier et la mémoire court terme, **Azure AI Foundry** (`gpt-5.6-terra`) pour le LLM,
**Azure AI Content Safety** pour les garde-fous prod.

## Provisionnement

Les ressources ont été créées **au portail** (groupe de ressources unique, région Sweden
Central) : App Service Plan + Web App, Flexible Server, Storage Account + partage Azure
Files, ACR. Le détail ressource par ressource, avec les justifications de choix, est dans
[`docs/dossier-deploiement-azure.md`](../docs/dossier-deploiement-azure.md) §1 et §5.

Le sidecar Chroma se déclare sur la Web App (*Deployment Center → Containers*) avec l'image
`chromadb/chroma:0.5.23`, le port 8001, et le partage Azure Files monté sur
`/chroma/chroma`. Sans ce montage, les faits durables repartent de zéro à chaque
redémarrage — c'est précisément le défaut que le déploiement corrige.

## Configuration

Tout passe par les **paramètres d'application** de la Web App (chiffrés au repos, injectés
en variables d'environnement au démarrage) — jamais dans le dépôt. La liste exhaustive,
secrets et configuration séparés, est dans
[`docs/dossier-deploiement-azure.md`](../docs/dossier-deploiement-azure.md) §3. L'essentiel :

| Variable | Valeur | Sensible |
|---|---|---|
| `DB_URL` | `postgresql+psycopg://<user>:<mdp>@<pg-server>.postgres.database.azure.com:5432/velmo?sslmode=require` | oui (mot de passe) |
| `AZURE_AI_INFERENCE_ENDPOINT` / `_MODEL` | endpoint Foundry / `gpt-5.6-terra` | non |
| `AZURE_AI_INFERENCE_API_KEY` | clé Foundry | oui |
| `AZURE_CONTENT_SAFETY_ENDPOINT` / `_KEY` | endpoint / clé Content Safety | la clé |
| `CHROMA_URL` | `http://localhost:8001` (le sidecar) | non |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` (baké dans l'image) | non |
| `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` | `1` — embeddings hors-ligne au runtime | non |
| `WEBSITES_PORT` | `8000` — le port que Streamlit expose à l'App Service | non |

Le build télécharge le modèle d'embedding depuis HuggingFace (il faut que HF soit joignable
**à ce moment-là**) ; le runtime, lui, est ensuite hors-ligne.

## Déployer

Automatisé et conditionné à la porte de qualité : un tag `v*.*.*` déclenche
[`release.yml`](../.github/workflows/release.yml) (éval + note globale, livraison bloquée
sous le seuil), et [`deploy.yml`](../.github/workflows/deploy.yml) ne démarre **que si
`release` a réussi**. Il construit l'image dans l'ACR et redémarre la Web App.
L'authentification est **OIDC** : aucun credential Azure n'est stocké dans le dépôt.

Repli manuel, depuis une session `az login` :

```bash
az acr build --registry <acr-name> --image velmo:<version> --image velmo:latest \
  --build-arg VELMO_VERSION=<version> .
az webapp restart -g <resource-group> -n <app-name>
az webapp show -g <resource-group> -n <app-name> --query defaultHostName -o tsv
```

## Rollback

Chaque déploiement pousse deux tags : `velmo:<version>` (immuable) et `velmo:latest` (celui
que la Web App tire au démarrage). Revenir en arrière consiste à repointer `latest` sur la
version précédente, puis redémarrer :

```bash
az acr import --name <acr-name> --source <acr-name>.azurecr.io/velmo:<version-précédente> \
  --image velmo:latest --force
az webapp restart -g <resource-group> -n <app-name>
```

## Journaux

Le **Log stream** de l'App Service donne stdout/stderr en temps réel — rien à provisionner,
seule la journalisation applicative est à activer :

```bash
az webapp log config -g <resource-group> -n <app-name> --application-logging filesystem
az webapp log tail   -g <resource-group> -n <app-name>
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
az containerapp secret set -g <resource-group> -n <app-name> --secrets lfsecret=<sk-lf-...>

az containerapp update -g <resource-group> -n <app-name> --set-env-vars \
  LANGFUSE_PUBLIC_KEY=<pk-lf-...> \
  LANGFUSE_SECRET_KEY=secretref:lfsecret \
  LANGFUSE_HOST=https://cloud.langfuse.com
```

Ce qui apparaît alors dans le dashboard, par tour : la latence, le coût (tokens
gpt-5.6-terra), la catégorie de garde-fou déclenchée, l'escalade et les erreurs d'outils.
Les tours d'un même client sont regroupés en conversation (`session_id`).

**Attention à ce que poser ces clés implique réellement.** Le message brut avant
masquage ne part jamais, et un message bloqué en entrée n'envoie aucun contenu (juste
son verdict, pour que le taux de blocage reste mesurable) — mais ce n'est *pas* la
même chose que « seul le message masqué est envoyé ». Le handler LangChain instrumente
tout le graphe, pas que le tour lui-même : ce qui atteint Langfuse Cloud inclut aussi
l'historique de conversation restauré du checkpointer (jusqu'à 30 messages) et la
réponse finale, qui peut légitimement contenir l'**email du client** (le garde-fou de
sortie bloque les emails d'un *autre* client, pas le sien). Et **dès qu'un tour passe
par le nœud LLM** — les tours traités en routage déterministe n'appellent aucun modèle
et n'en produisent rien — s'y ajoutent le prompt système avec les faits mémoire
injectés pour ce client, et le contenu des appels d'outils, y compris l'**adresse de
livraison** (`order_to_dict` la renvoie en clair).
Le hook de masquage à l'export (`mask_otel_spans`) ne rattrape que les numéros
de carte (Luhn valide) et les IBAN, la même détection que le garde-fou d'entrée —
il ne masque ni les adresses, ni les emails, ni les faits mémoire stockés.

Concrètement : activer `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` en prod revient à
envoyer à Langfuse Cloud (service externe, hors du périmètre Postgres/Chroma) le
contenu métier de la conversation de chaque client — pas seulement des métriques
agrégées. C'est un compromis assumé pour obtenir coût et latence par tour sans
instrumentation manuelle ; ce n'est pas une anonymisation de la conversation.
`GuardrailEngine.events` (le journal de conformité) reste, lui, strictement local —
seules des métadonnées agrégées (action, catégorie) partent sur la trace.

Le gate d'éval en CI reste **hors-ligne** et n'interroge jamais Langfuse, par
construction : `velmo.mlops.score` (sans `--prod`) construit l'agent avec
`tracer=NoOpTracer()` explicitement, indépendamment des variables `LANGFUSE_*`
présentes ou non sur la machine qui l'exécute — la note bloquante doit rester
déterministe et sans dépendance réseau.

## Qualité des réponses (évaluateur Langfuse)

Le score livré par le chantier 005d est **`relevance`** : la réponse répond-elle à la
question posée ? Il est produit par un **évaluateur Langfuse**, pas par du code de ce
dépôt — le scoring est de la configuration dans l'interface, ce qui est précisément
pourquoi ce chantier n'ajoute aucune dépendance.

`relevance` n'a besoin que de deux champs, `query` et `generation`, tous deux portés
par l'observation racine `handle-turn`. Rien à mapper d'exotique.

Prérequis : les clés Langfuse sont posées (section précédente), et une **LLM
Connection** est configurée dans Langfuse (Settings → LLM Connections) avec un modèle
supportant les **sorties structurées**. Vérifié en pratique avec `gpt-5.6-terra` via Azure
Foundry.

1. Dans le projet Langfuse : créer un évaluateur à partir du template **relevance**
   du catalogue.
2. Cibler les **observations**, filtrées sur le nom `handle-turn` — l'observation
   racine d'un tour, celle qui porte le message client et la réponse finale.
3. Mapper les deux variables, sans JsonPath (ce sont des chaînes plates) :
   - `query` → Object Field **Input** ;
   - `generation` → Object Field **Output**.
   L'aperçu en direct montre le prompt rempli avec de vraies données ; « Input: » y est
   un titre de section du prompt du juge, pas un champ vide.
4. Régler l'échantillonnage (5 à 10 % suffit en régime permanent ; 100 % est
   raisonnable le temps de quelques messages de test) et activer.

**L'évaluateur ne rejoue pas le passé.** Les scores se posent à l'arrivée de la
donnée : une trace déjà présente au moment de l'activation ne sera jamais notée. Pour
vérifier que ça marche, envoyer un **nouveau** message, puis ouvrir cette trace →
observation `handle-turn` → le score et le raisonnement du juge y sont attachés.

**Exclure les tours bloqués.** Un message refusé par le garde-fou d'entrée apparaît
comme `[blocked input]` → `[refused]`. Un juge de pertinence le note ~0, alors que le
refus est le comportement correct. Filtrer sur la métadonnée `guardrail_in` pour les
sortir de l'échantillon, sinon ils tirent la moyenne vers le bas sans rien vouloir dire.

**Où lire les échecs.** Ils ne sont pas sur la trace applicative : chaque exécution du
juge crée **sa propre trace**. Filtrer le tableau des traces sur l'environnement
`langfuse-llm-as-a-judge` donne le statut de chaque évaluation (`Completed`, `Error`,
`Delayed` pour un rate limit, `Pending`). Aucune ligne du tout = l'évaluateur n'a
jamais été déclenché.

### Pourquoi pas `faithfulness`

Le chantier expose bien l'observation `retrieve-memory` (type `retriever`), qui rend
enfin visible ce que la recherche mémoire a récupéré — précieux pour déboguer une
mauvaise réponse. Mais `faithfulness` n'est **pas** activé, pour deux raisons établies
en le configurant pour de vrai :

1. **Langfuse ne peut pas le câbler.** Un évaluateur au niveau observation ne voit que
   l'observation qu'il cible : la documentation précise qu'il « ne charge pas les
   observations sœurs ou filles de la même trace ». Impossible donc de cibler la
   `generation` tout en lisant le `contexts` sur `retrieve-memory`. Il faudrait
   recopier les documents sur l'observation racine.
2. **Il mesurerait la mauvaise chose.** Le contexte mémoire, ce sont des faits sur le
   client (`taille : fait du L`), pas la source des réponses. L'agent se fonde sur la
   FAQ (`search_kb`) et sur Postgres. Un juge `faithfulness` nourri des faits mémoire
   noterait « non fidèles » des réponses correctes — d'autant que la mémoire part vide
   et le reste longtemps pour un nouveau client.

Le vrai risque d'hallucination du produit est d'inventer une politique de retour ou un
délai de livraison, donc la **FAQ**. Mesurer ça demanderait d'exposer les résultats de
`search_kb` sur l'observation racine — un chantier à part, pas fait ici.

**Ce qui n'est pas scoré, et pourquoi.** Les tours traités par le **routage
déterministe** répondent par un gabarit sans appeler de modèle. Ils portent quand même
un `handle-turn`, donc ils entrent dans l'échantillon : leur score de pertinence est
lisible, mais il mesure la qualité des gabarits, pas celle du LLM.

**Le gate CI reste hors-ligne.** Ces scores vivent sur les traces de production et
n'entrent jamais dans `mlops/report.md` : faire dépendre la note bloquante d'un juge
LLM la rendrait non déterministe, l'inverse de ce que garantit le chantier 005a.
