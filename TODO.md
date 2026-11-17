# Migration — FastAPI + Vue

- [x] Exposer la topologie, les états, les logs et les actions via FastAPI.
- [x] Valider les topologies avec des modèles Pydantic.
- [x] Conserver l’orchestrateur indépendant du transport HTTP.
- [x] Créer le frontend Vue 3 + TypeScript + Vite.
- [x] Migrer l’éditeur visuel et la sauvegarde vers Vue.
- [x] Ajouter le contrat de santé `/health` et la documentation OpenAPI.
- [x] Vérifier les tests backend et le build frontend.
- [x] Remplacer l’interface legacy après validation et supprimer l’ancien serveur/interface.
- [x] Ajouter un WebSocket pour le terminal, les sorties et la fermeture de session.
- [x] Ajouter les versions locales, restauration, clonage et export/import JSON.
- [ ] Migrer la persistance vers PostgreSQL lorsque plusieurs utilisateurs seront supportés.
- [ ] Ajouter utilisateurs, rôles et laboratoires cloud.
- [x] Séparer FastAPI du worker Docker avec un contrat de jobs et un token de développement.
- [ ] Ajouter une file de tâches, des identités de workers, des quotas et mTLS.
