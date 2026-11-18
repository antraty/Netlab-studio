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
