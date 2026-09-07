# Contexte du projet
Vous avez reconstruit Velmo 2.0, l'agent de support de la boutique de maillots collector. Il tient enfin ses trois promesses : une mémoire exemplaire (fil de conversation + faits durables du client, isolés par utilisateur), des garde-fous sérieux en entrée et en sortie, et une qualité mesurée à chaque version.

Problème : tout cela ne tourne que sur votre machine, en local.

La semaine dernière, la direction de Velmo a voulu faire tester l'agent par deux vendeurs depuis leurs propres postes. Impossible : rien n'était accessible en ligne, et la mémoire long terme était stockée dans un simple fichier local — donc perdue dès qu'on changeait de machine. La CTO vous confie la mise en production : déployer Velmo 2.0 sur Azure, en le branchant au service d'IA d'Azure (Azure OpenAI / Azure AI Foundry), avec une mémoire long terme réellement persistante et partagée, et sans jamais exposer les secrets. Interdiction de dégrader les garde-fous ou la mémoire au passage : ce qui marchait en local doit marcher en ligne.

# Modalités pédagogiques
• Format : binôme (pair-programming) ou petite équipe.

• Durée estimée : 2 jours.

## Travail préliminaire de conception
La conception se mène avant tout code et doit être validée par le formateur. Elle produit un dossier de déploiement (schémas + tableaux ci-dessous).

1- Choisir les services Azure pour héberger l'agent et sa mémoire
À partir de l'architecture de Velmo 2.0 et de la ressource fournie, l'apprenant sera capable de sélectionner et justifier les services Azure adaptés à l'hébergement de l'agent, de sa mémoire persistante et de son service d'IA.

• Comparer les options d'hébergement de l'agent (App Service vs conteneur) sur des critères simples : facilité, coût, adéquation.

• Choisir un service de stockage persistant pour la mémoire long terme (base de données / stockage managé Azure) répondant aux exigences R2 (persistance) et R3 (isolation par utilisateur).

2- Concevoir la gestion des secrets et de la configuration
À partir des exigences de sécurité de Velmo 2.0, l'apprenant sera capable de définir comment les secrets (clé Azure OpenAI, chaîne de connexion mémoire) sont configurés hors du code.

• Lister les secrets et paramètres à externaliser (clé et endpoint du service d'IA, connexion au stockage mémoire, seuils des garde-fous).

• Décrire où et comment ils seront stockés côté Azure (variables d'application, et/ou coffre de secrets), sans jamais figurer dans le dépôt Git.

Critères d'évaluation

• La liste des secrets à externaliser est complète.

• Le mécanisme de stockage des secrets côté Azure est décrit et exclut toute présence dans le code

source.

3- Établir le schéma de déploiement cible
À partir du schéma d'architecture global de Velmo 2.0, l'apprenant sera capable de concevoir le schéma de déploiement Azure correspondant, en préservant la chaîne garde-fous → mémoire → LLM.

• Dessiner le schéma cible : navigateur → App Service / Conteneur (garde-fou d'entrée → mémoire lecture →

Azure OpenAI → garde-fou de sortie → mémoire écriture) → stockage mémoire persistant.

• Indiquer sur le schéma où passent les secrets et où sont lus/écrits les journaux.

## Développement
Une fois le dossier de déploiement validé, mettre Velmo 2.0 en production sur Azure.

4- Provisionner les ressources Azure
À partir du dossier de déploiement, l'apprenant sera capable de créer et d'organiser les ressources Azure

nécessaires (hébergement, stockage mémoire, service d'IA) dans un groupe de ressources unique.

Activité

• Créer un groupe de ressources dédié (ex. rg-velmo-prod) en région France Central / Sweden Central.

• Provisionner l'App Service / Conteneur, le stockage persistant de la mémoire et la ressource Azure OpenAI / AI

Foundry.

• Déployer le modèle choisi dans le service d'IA.

5- Déployer l'agent et le connecter au service d'IA
À partir du dépôt de Velmo 2.0, l'apprenant sera capable d'adapter le déploiement de l'agent sur l'App

Service et de le connecter au service d'IA Azure via une configuration sécurisée.

Activité

• Déployer le code de Velmo 2.0 sur l'App Service/ Conteneur et obtenir une URL publique.

• Renseigner la clé et l'endpoint Azure OpenAI dans les variables d'application (jamais dans le code) et

vérifier une conversation en ligne.

6- Rendre la mémoire long terme persistante et isolée en ligne
À partir du modèle mémoire de Velmo 2.0, l'apprenant sera capable de brancher la mémoire long terme

sur le stockage persistant Azure en préservant la persistance inter-session (R2) et l'isolation par utilisateur

(R3).

• Connecter la mémoire long terme au stockage Azure via la chaîne de connexion configurée en secret.

• Vérifier qu'un fait donné en session 1 est retrouvé en session 2, et qu'un second utilisateur n'y a pas accès.

7- Vérifier les garde-fous et la sécurité en production
À partir des tests d'acceptance de Velmo 2.0, l'apprenant sera capable de contrôler que les garde-fous et

la protection des secrets restent effectifs une fois l'agent en ligne.

• Rejouer en ligne quelques cas de garde-fou (message à bloquer, injection de prompt, PII en sortie) et

constater le blocage + la journalisation.

• Vérifier qu'aucun secret ni donnée de configuration n'est exposé dans les réponses ou les pages de

l'application.

8- Mettre en place les premiers signaux de suivi en production
À partir des journaux et métriques de l'App Service / Conteneur, l'apprenant sera capable d'intégrer des signaux de

suivi de base pour surveiller l'agent en exploitation.

• Activer et consulter les journaux de l'application (Log stream) et repérer latence et erreurs.

• Relever des signaux simples de suivi : latence par conversation, coût indicatif, taux de blocage des

garde-fous.

9- Documenter et présenter la mise en production
À partir du travail réalisé, l'apprenant sera capable de rédiger la documentation de déploiement et de

présenter la mise en production au commanditaire.

• Rédiger un runbook « Déployer et exploiter Velmo 2.0 sur Azure » (étapes, secrets, mémoire, suivi).

• Présenter en 5-10 minutes l'agent en ligne, la persistance mémoire, les garde-fous et les signaux de

suivi à un pair jouant la CTO.

# Modalités d'évaluation
• Validation du dossier de déploiement (porte d'entrée) avant toute mise en ligne.
• Passage des tests d'acceptance en ligne (mémoire persistante, isolation, garde-fous, secrets).
• Revue de code + démonstration de l'agent déployé depuis son URL publique.
• Auto-évaluation et co-évaluation Simplonline.

# Livrables
• URL publique de Velmo 2.0 déployé sur Azure App Service / Conteneur . 
• Dossier de déploiement : schéma cible + liste des secrets externalisés + plan de la mémoire
persistante.
• Dépôt Git à jour + runbook « Déployer et exploiter Velmo 2.0 sur Azure ».
• Capture du portail Azure montrant le groupe de ressources (App Service/Conteneur, stockage mémoire, Azure
OpenAI).
• Court relevé des signaux de suivi (latence, coût, taux de blocage garde-fous).

# Critères de performance
• L'agent est accessible publiquement via son URL Azure et répond via le service d'IA Azure.
• La mémoire long terme persiste d'une session à l'autre et reste strictement isolée par utilisateur (R2,
R3).
• Les garde-fous validés en local restent effectifs en ligne (entrée et sortie).
• Aucun secret (clé Azure OpenAI, connexion mémoire) n'est présent dans le code : tout est
externalisé côté Azure.
• Les ressources sont regroupées dans un groupe de ressources unique, facile à retrouver et à
supprimer.