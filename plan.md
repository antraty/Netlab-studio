# Migration FastAPI + Vue

## Objectif

Remplacer progressivement le serveur `http.server` et l’interface JavaScript vanilla par une API FastAPI et une application Vue 3 + TypeScript + Vite, sans réécrire l’orchestrateur Docker.

## Décisions

- `backend/app/` contient le plan de contrôle HTTP et les modèles Pydantic.
- `orchestrator.py` reste le plan d’exécution et l’adaptateur Docker.
- `frontend/` contient l’éditeur et consomme uniquement l’API HTTP.
- L’ancien serveur HTTP et l’ancienne interface vanilla ont été supprimés après validation de la stack migrée.
- La persistance fichier JSON est conservée pour le prototype ; PostgreSQL sera ajouté quand les utilisateurs et laboratoires multiples seront introduits.

## Structure cible

```text
backend/app/       FastAPI, modèles, routes et dépendances
orchestrator.py    interface d’exécution Docker/VM/worker
frontend/src/      Vue 3, TypeScript, stores et composants de topologie
topology.json      exemple versionné de laboratoire
```

## Style de l’interface

Direction « console de laboratoire » : sombre, technique et lisible, avec le vert menthe comme signal d’état actif. Les graphes et terminaux restent prioritaires sur les éléments décoratifs. L’éditeur doit favoriser la manipulation directe de la topologie et rendre les états d’exécution immédiatement visibles.
