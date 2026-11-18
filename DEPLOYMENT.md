# Démarrage reproductible avec Docker Compose

Ce profil démarre le socle opérationnel de Netlab Studio : un frontend Vue servi par Nginx, une API FastAPI, un worker Docker séparé et PostgreSQL.

## Prérequis

- Docker Engine récent avec le plugin `docker compose` ;
- au moins 4 Go de mémoire disponibles ;
- un accès au registre Docker pour construire les images et télécharger PostgreSQL ;
- les images de laboratoire construites avant le premier déploiement :

```bash
docker build -t netlab/ubuntu-lab:24.04 images/ubuntu-lab
docker build -t netlab/debian-lab:bookworm images/debian-lab
docker build -t netlab/debian-router:bookworm images/debian-router
```

## Lancement local

```bash
cp .env.example .env
# Remplacer au minimum les trois valeurs replace-with-*.
docker compose up --build -d

docker compose ps
# Interface : http://localhost:8080
# Santé de la pile : http://localhost:8080/health
```

Le premier compte enseignant est créé depuis l’interface avec `NETLAB_BOOTSTRAP_TOKEN`. Le worker et PostgreSQL ne sont pas publiés sur l’hôte. Seul le frontend expose le port HTTP 8080 par défaut.

Arrêt et suppression des conteneurs :

```bash
docker compose down
```

Pour supprimer également les données PostgreSQL et Netlab, utiliser explicitement `docker compose down -v`.

## Flux réseau

```text
Navigateur -> frontend:Nginx -> control:8000 -> worker:9000 -> Docker socket
                                      |
                                      +-> db:5432
```

Le socket Docker est monté uniquement dans le worker. Le plan de contrôle n’exécute donc pas directement de commande Docker lorsqu’il utilise `NETLAB_WORKER_URL`.

## Services de données — Tranche 2

Les profils `postgresql`, `mysql` et `mongodb` sont déployables depuis l’éditeur. Ils utilisent respectivement les images `postgres:17-alpine`, `mysql:8.4` et `mongo:8`, des limites de ressources, un healthcheck et un volume Docker nommé par laboratoire et par nœud. `docker compose down` conserve ces volumes ; `docker compose down -v` les supprime.

Une topologie ne doit jamais contenir la valeur d’un mot de passe. Elle référence un secret :

```json
{
  "service_id": "postgresql",
  "image": "postgres:17-alpine",
  "command": ["postgres"],
  "environment": {"POSTGRES_USER": "lab", "POSTGRES_DB": "training"},
  "secret_refs": {"POSTGRES_PASSWORD": "lab-password"},
  "depends_on": []
}
```

La valeur correspondante doit être placée dans le fichier `.env` local du Compose :

```env
NETLAB_SECRET_LAB_PASSWORD=une-valeur-secrete-longue
```

Le worker lit cette variable, génère un fichier runtime temporaire en mode `0600` et le transmet à Docker. Le fichier est supprimé avec les autres fichiers runtime lors de l’arrêt du laboratoire. Les variables exigées par chaque profil sont visibles dans le catalogue et dans l’éditeur ; les références de secrets ne sont jamais affichées comme des valeurs.

`depends_on` impose l’ordre de démarrage dans la topologie et les cycles sont refusés. Il s’agit d’un ordre d’exécution du laboratoire, distinct de `depends_on` de Docker Compose qui démarre les services de la plateforme.

## Production

Le fichier Compose fournit un environnement local reproductible, pas une exposition Internet prête à l’emploi. Avant une exposition publique :

1. utiliser un reverse-proxy HTTPS devant le frontend ;
2. définir `NETLAB_ENV=production`, `NETLAB_COOKIE_SECURE=true` et des origines HTTPS ;
3. remplacer PostgreSQL local par une instance TLS avec `sslmode=require` ou plus strict ;
4. utiliser des secrets aléatoires d’au moins 32 caractères pour le mot de passe PostgreSQL, le token worker et le token bootstrap ;
5. remplacer les tags d’images mutables par des digests vérifiés et scanner les images ;
6. restreindre le socket Docker et le réseau du worker, puis planifier sa rotation et sa supervision ;
7. ne jamais publier les ports 8000, 9000 ou 5432.

La validation de production bloque volontairement une configuration HTTP ou PostgreSQL non chiffrée. Le profil Compose reste en mode `development` par défaut pour que le démarrage local fonctionne avec `http://localhost:8080`.

## Comptes, invitations et remises

Le premier compte peut être administrateur avec :

```env
NETLAB_BOOTSTRAP_TOKEN=un-secret-aleatoire-d-au-moins-32-caracteres
NETLAB_BOOTSTRAP_ROLE=admin
```

Sans cette variable, le premier compte est enseignant. Les rôles disponibles sont administrateur, enseignant et étudiant.

- les administrateurs peuvent inviter des enseignants ;
- les enseignants peuvent inviter des étudiants, éventuellement dans un groupe existant ;
- les invitations sont à usage unique et expirent après 7 jours ;
- les réinitialisations de mot de passe sont à usage unique et expirent après 1 heure ;
- les jetons sont affichés une fois puis conservés uniquement sous forme d’empreintes ;
- aucune remise e-mail n’est effectuée : transmettre le jeton hors du dépôt, par un canal sûr.

Les affectations peuvent inclure des consignes, des critères et un modèle de laboratoire. Chaque remise crée une tentative avec un instantané. La correction peut ajouter un commentaire et une note de 0 à 100. La réinitialisation demandée par l’étudiant arrête d’abord son runtime, puis restaure une copie neuve conforme au modèle sans effacer l’historique des tentatives.
