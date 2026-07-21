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
supportant les **sorties structurées**. Vérifié en pratique avec `Kimi-K2.6` via Azure
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
