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
make setup
make up

docker compose ps
# Interface : http://localhost:8080
# Santé de la pile : http://localhost:8080/health
make ps
```

Le premier compte enseignant est créé depuis l’interface avec `NETLAB_BOOTSTRAP_TOKEN`. Le worker et PostgreSQL ne sont pas publiés sur l’hôte. Seul le frontend expose le port HTTP 8080 par défaut.

Les variables `NETLAB_WORKER_URL` et `NETLAB_CONTROL_URL` de `.env` servent au lancement direct des services sur l’hôte. Compose utilise séparément `NETLAB_COMPOSE_WORKER_URL` et `NETLAB_COMPOSE_CONTROL_URL` (par défaut `http://worker:9000` et `http://control:8000`) pour la communication DNS interne. Ne remplacez pas ces URL Compose par `127.0.0.1` : dans un conteneur, cette adresse référence le conteneur lui-même.

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

1. utiliser un reverse-proxy/ingress HTTPS devant le frontend et le plan de contrôle ;
2. définir `NETLAB_ENV=production`, `NETLAB_COOKIE_SECURE=true` et des origines HTTPS ;
3. utiliser PostgreSQL managé ou redondé avec TLS (`sslmode=verify-full` recommandé) et sauvegardes ;
4. utiliser des secrets aléatoires d’au moins 32 caractères pour le mot de passe PostgreSQL, le token worker et le token bootstrap ;
5. remplacer les tags d’images mutables par des digests vérifiés et scanner les images ;
6. configurer le mTLS obligatoire dans les deux sens entre le plan de contrôle et les workers ; injecter les certificats comme secrets montés en lecture seule ;
7. restreindre le socket Docker et les réseaux workers, puis planifier leur rotation et supervision ;
8. ne jamais publier directement les ports 8000, 9000 ou 5432.

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

## Exécution distante — Tranche 4

Le plan de contrôle utilise une file persistante PostgreSQL pour les travaux `up`, `down`, `verify`, `status`, `terminal` et `observability`. Les jobs sont placés en location avec un identifiant de worker, jusqu’à trois tentatives par défaut, puis repris après expiration de leur bail.

Chaque worker publie son identifiant, son nom, ses capacités et son heartbeat. Les workers sans heartbeat depuis 90 secondes passent hors ligne. Les durées, codes de sortie et résultats sont conservés dans les métriques d’exécution ; les échecs créent une alerte persistante consultable depuis l’API.

Le worker est exposé uniquement sur le réseau interne Compose. En production :

1. utiliser HTTPS pour `NETLAB_WORKER_URL` ;
2. fournir les certificats CA, certificat et clé mTLS client ;
3. fournir les certificats serveur avec `NETLAB_MTLS_SERVER_*` ;
4. conserver un jeton worker distinct à haute entropie ;
5. identifier chaque worker avec `NETLAB_WORKER_ID` et `NETLAB_WORKER_NAME`.

Les jobs échoués sont retentés avec un backoff borné. Les leases expirés sont remis automatiquement en file. Les laboratoires expirés sont nettoyés jusqu’à trois fois ; chaque tentative est enregistrée avec son résultat et son erreur.

## Étape D — base TLS, migration et workers redondants

### Migrer SQLite vers PostgreSQL

La cible doit être une base PostgreSQL vide. Faites une sauvegarde de la source SQLite et conservez le fichier intact pendant la migration. Définissez une URL PostgreSQL avec TLS et le certificat CA de confiance, puis lancez le migrateur depuis la racine du projet :

```bash
export NETLAB_DATABASE_URL='postgresql://netlab:mot-de-passe@postgres.example.org:5432/netlab?sslmode=verify-full&sslrootcert=/run/secrets/postgres-ca.crt'
.venv/bin/python -m backend.app.migrate_db --source .netlab-data/education.sqlite3
```

Le migrateur refuse une cible contenant déjà des comptes et copie aussi les workers, jobs, métriques, alertes, données de licences, snapshots, journaux et données pédagogiques. Gardez une sauvegarde PostgreSQL et vérifiez les nombres de comptes/laboratoires avant de basculer le service. Les versions conservées uniquement sous forme de fichiers doivent aussi être disponibles via le stockage de `NETLAB_DATA_DIR`.

### mTLS entre services

Le mode `NETLAB_ENV=production` refuse maintenant de démarrer sans mTLS configuré :

- le plan de contrôle utilise `NETLAB_MTLS_CA_FILE`, `NETLAB_MTLS_CERT_FILE` et `NETLAB_MTLS_KEY_FILE` pour appeler le worker ;
- le worker sert HTTPS avec `NETLAB_MTLS_SERVER_CERT_FILE`, `NETLAB_MTLS_SERVER_KEY_FILE` et `NETLAB_MTLS_SERVER_CA_FILE`, et exige le certificat client ;
- les callbacks du worker vers le plan de contrôle utilisent `NETLAB_CONTROL_MTLS_CA_FILE`, `NETLAB_CONTROL_MTLS_CERT_FILE` et `NETLAB_CONTROL_MTLS_KEY_FILE`, avec `NETLAB_CONTROL_URL` en HTTPS.

Les certificats ne doivent pas être placés dans le dépôt ou dans les images. Les fournir par gestionnaire de secrets ou volumes montés en lecture seule. La terminaison HTTPS/mTLS du plan de contrôle doit être configurée sur l’ingress/reverse proxy : il doit valider le certificat client des workers, et `NETLAB_CONTROL_URL` doit pointer sur ce endpoint interne. Les fichiers d’exemple indiquent les chemins de conteneur attendus. Ne pas désactiver la validation CA ou hostname.

### Réplicas et limites opérationnelles

- Plusieurs workers peuvent interroger la même file PostgreSQL : les claims utilisent `FOR UPDATE SKIP LOCKED` et un index de file. Laisser `NETLAB_WORKER_ID` vide pour que chaque instance s’identifie avec son hostname unique.
- Les heartbeats du worker continuent pendant l’exécution d’un job pour renouveler son lease. Après arrêt brutal, un lease expiré permet une nouvelle tentative ; une action longue peut donc être rejouée et doit être considérée comme *at-least-once*.
- Plusieurs instances de contrôle doivent partager PostgreSQL et le même stockage durable pour `NETLAB_DATA_DIR`. Un volume Docker local n’est pas un stockage partagé entre hôtes.
- La réplication de worker n’est sûre que si ces workers opèrent sur le moteur Docker visé et partagent les mêmes ressources de laboratoire ; une flotte multi-hôtes requiert un routage de jobs par capacité/placement et un moteur d’exécution distribué, pas simplement davantage de réplicas Compose.
- La file persistante n’assure pas à elle seule une HA complète : déployer aussi un ingress/redémarrage automatique, sauvegardes régulières et restaurations éprouvées, supervision PostgreSQL et tests de panne avant toute mise en service publique.

## Préparation KVM/libvirt

Avant la tranche 5, les topologies acceptent les champs préparatoires `backend`, `cpu_cores`, `memory_mb`, `disk_gb`, `license_id` et `console`. Le backend est limité à `docker` ou `libvirt`; tout choix libvirt échoue explicitement tant que l’adaptateur VM n’est pas installé.

- les limites VM sont contrôlées par laboratoire ;
- les licences doivent être enregistrées par un administrateur ;
- l’utilisateur doit accepter une licence active avant tout démarrage ;
- les snapshots, sessions console et restaurations sont audités ;
- les accès console ne deviennent disponibles qu’après authentification et autorisation du laboratoire ;
- aucun accès VNC, SPICE, RDP ou SSH n’est rendu disponible par défaut.
