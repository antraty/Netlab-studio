# Migration FastAPI + Vue

## Objectif

Remplacer progressivement le serveur `http.server` et l’interface JavaScript vanilla par une API FastAPI et une application Vue 3 + TypeScript + Vite, sans réécrire l’orchestrateur Docker.

## Décisions

- `backend/app/` contient le plan de contrôle HTTP et les modèles Pydantic.
- `orchestrator.py` reste le plan d’exécution et l’adaptateur Docker.
- `frontend/` contient l’éditeur et consomme uniquement l’API HTTP.
- Pour les topologies v2, l’éditeur expose directement les segments Docker, les interfaces IPv4 et les routes statiques ; la validation serveur reste l’autorité avant sauvegarde ou déploiement.
- L’ancien serveur HTTP et l’ancienne interface vanilla ont été supprimés après validation de la stack migrée.
- Les comptes, sessions, affectations et topologies courantes utilisent PostgreSQL si `NETLAB_DATABASE_URL` est défini, sinon SQLite reste disponible pour le prototype local.
- Les versions immuables de topologie restent dans `NETLAB_DATA_DIR` ; elles ne sont pas encore partagées entre plusieurs serveurs.
- Chaque laboratoire possède un UUID, des rôles de membre et un cycle de vie/quota persistés. Les ressources d’exécution Docker utilisent cet identifiant dans leurs labels.

## Structure cible

```text
backend/app/       FastAPI, modèles, routes et dépendances
orchestrator.py    interface d’exécution Docker/VM/worker
frontend/src/      Vue 3, TypeScript, stores et composants de topologie
topology.json      exemple versionné de laboratoire
```

## Style de l’interface

Direction « console de laboratoire » : sombre, technique et lisible, avec le vert menthe comme signal d’état actif. Les graphes et terminaux restent prioritaires sur les éléments décoratifs. L’éditeur doit favoriser la manipulation directe de la topologie et rendre les états d’exécution immédiatement visibles.

## Évolution éditeur visuel — option B

L’éditeur évolue vers une expérience de type Packet Tracer, sans remplacer l’exécution réelle Docker :
- une palette permet de glisser des PC Linux, routeurs, serveurs et profils applicatifs vers le canvas ;
- les nœuds sont positionnés directement sur le plan et affichent des ports réseau ;
- un clic sur deux ports crée un câble visuel et synchronise les interfaces avec le segment du premier port ;
- un switch virtuel est représenté dans cette première étape par l’ajout d’un segment Docker bridge ;
- les propriétés détaillées restent disponibles dans le panneau réseau existant, avant une migration vers des fenêtres contextuelles par équipement.

Le canvas est une couche d’intention utilisateur : il produit toujours une topologie JSON validée par FastAPI. Les liens visuels et les interfaces réseau doivent rester cohérents avec le plan d’exécution Docker ; les appliances réseau et les ports de switch avancés seront traités dans une étape ultérieure.
