# Prototype technique — étape 1

Ce prototype couvre les quatre objectifs initiaux du README :

1. définir une topologie versionnée en JSON ;
2. créer un réseau Docker `bridge` ;
3. lancer un client Ubuntu et un serveur Debian ;
4. vérifier leur connectivité réelle depuis le client.

## Prérequis

- Python 3.10 ou plus récent ;
- Docker Engine et le Docker CLI ;
- un accès au registre Docker pour télécharger `ubuntu:24.04` et `debian:bookworm-slim`.

Le prototype ne nécessite pas de paquet Python externe.

## Utilisation

```bash
python3 netlab.py topology.json validate
python3 netlab.py topology.json up
python3 netlab.py topology.json verify
python3 netlab.py topology.json down
```

`up` crée un réseau dédié au laboratoire et relance proprement les deux conteneurs avec des noms déterministes. `verify` exécute la commande `ping` définie dans la topologie à l’intérieur du conteneur source. Les images de démonstration doivent donc fournir `ping`; si ce n’est pas le cas, le message Docker est retourné tel quel pour rendre le problème explicite.

## Format de topologie v1

Le fichier `topology.json` constitue l’exemple canonique. Il contient :

- `version` et `lab` pour identifier le format et le laboratoire ;
- `network` pour le réseau virtuel ;
- `nodes` pour les conteneurs et leur commande de maintien en vie ;
- `connectivity_check` pour le test réseau reproductible.

Cette séparation prépare la future API de contrôle : le JSON décrit l’intention du laboratoire, tandis que `netlab.py` réalise les opérations du plan d’exécution.

## Tests locaux

La validation et les tests de schéma ne requièrent pas Docker :

```bash
python3 -m unittest -v
```

## Étapes 2 et 3 — API FastAPI et éditeur Vue

Le plan de contrôle et l’éditeur sont maintenant servis par FastAPI et Vue :

```bash
export NETLAB_BOOTSTRAP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
# ouvrir http://127.0.0.1:5173
```

Avant le premier lancement de FastAPI, définir `NETLAB_BOOTSTRAP_TOKEN` avec un jeton aléatoire fort. L’interface l’utilise une fois pour créer le compte enseignant initial ; aucune inscription publique n’est disponible.

L’interface permet de charger la topologie, déplacer/ajouter/supprimer/relier les nœuds, déployer ou arrêter le laboratoire, lancer le test de connectivité, afficher les états et enregistrer la topologie. Les contrats sont validés par Pydantic et l’orchestration reste dans `orchestrator.py`.

L’API HTTP expose les routes suivantes :

- `GET /api/topology`, `POST /api/topology` ;
- `GET /api/status` et `GET /api/logs` ;
- `POST /api/up`, `/api/verify` et `/api/down` ;
- `POST /api/nodes/<nom>/terminal` pour les commandes ponctuelles de compatibilité ;
- `WS /ws/nodes/<nom>/terminal` pour le terminal interactif.

Les routes de laboratoire et le terminal sont réservés aux sessions enseignant. Les requêtes de modification utilisent un cookie CSRF ; les origines navigateur sont limitées par `NETLAB_ALLOWED_ORIGINS`. Cette protection est une base locale seulement et ne rend pas l’application apte à une exposition publique.

## Étape 2 — séparation du contrôle et de l’exécution

FastAPI joue le rôle de plan de contrôle et délègue les opérations à `DockerOrchestrator` dans `orchestrator.py`. Cette frontière permet de conserver la même API lorsqu’un moteur distant, une exécution sur VM ou un autre adaptateur sera ajouté. Le navigateur ne parle donc pas directement au CLI Docker.

## Début de l’étape 3 — éditeur visuel

L’interface comprend maintenant un éditeur SVG local : les nœuds sont déplaçables, un nouveau nœud peut être ajouté, deux nœuds peuvent être reliés et le nœud sélectionné peut être supprimé. Les positions et les liens sont conservés dans la topologie JSON (`position` sur les nœuds et `links` au niveau de la topologie).

La sauvegarde utilise toujours `POST /api/topology`. Les liens représentent actuellement la topologie visuelle ; le moteur Docker utilise encore un réseau `bridge` partagé. La traduction de chaque lien en interfaces et réseaux isolés fera partie de l’évolution du plan d’exécution.

## Étape 4 — terminal WebSocket

`backend/app/terminal.py` ouvre une session `docker exec -i ... sh -i` par connexion WebSocket. Les entrées du navigateur sont envoyées au shell et les sorties sont transférées en continu grâce à un lecteur dédié. La fermeture de la page arrête proprement le processus et ferme les flux.

Cette première version est volontairement locale. Avant un déploiement cloud, il faudra ajouter l’authentification, l’autorisation par laboratoire, les quotas, les limites de durée et une isolation renforcée des processus.

## Étape 6 — séparation FastAPI / worker Docker

`worker/main.py` est un second service FastAPI qui reçoit des jobs authentifiés par `Authorization: Bearer <token>`. Il est le seul composant qui appelle `DockerOrchestrator` et qui doit, à terme, avoir accès au socket Docker. Le plan de contrôle sélectionne ce worker avec `NETLAB_WORKER_URL` et `NETLAB_WORKER_TOKEN`; sans ces variables, il conserve le mode Docker local pour le développement.

Le contrat actuel couvre les actions `up`, `down`, `verify`, `status` et `terminal` ponctuel. Le terminal WebSocket reste local pour l’instant ; son équivalent distant nécessitera un canal de streaming dédié. Cette séparation prépare les workers cloud sans prétendre encore fournir l’isolation multi-tenant.

## Étape 5 — sauvegarde, restauration et reproductibilité

`backend/app/storage.py` conserve maintenant les définitions de topologie dans `.netlab-data/` sous forme de versions immuables. Une sauvegarde crée une nouvelle version, une restauration crée une nouvelle version à partir d’une version précédente, et le clonage donne un nouveau laboratoire indépendant. L’état temporaire des conteneurs n’est pas mélangé à ces fichiers : il reste fourni par l’orchestrateur Docker.

L’API expose `GET /api/laboratories/<lab>/versions`, `POST /api/laboratories/<lab>/restore/<version>`, `POST /api/laboratories/<lab>/clone`, `GET /api/laboratories/<lab>/export` et `POST /api/laboratories/import`. L’interface Vue propose les boutons de nouvelle version, restauration, clonage, export et import JSON.

## Étape 7 — prototype d’usage pédagogique

Le compte enseignant initial est créé uniquement si `NETLAB_BOOTSTRAP_TOKEN` est défini et si aucun utilisateur n’existe. Les mots de passe sont hachés avec PBKDF2-HMAC-SHA256 ; les sessions sont aléatoires, conservées sous forme de hachage dans SQLite et transmises par cookie `HttpOnly`, avec un cookie CSRF distinct. `NETLAB_COOKIE_SECURE=true` active l’attribut `Secure` quand l’application tourne derrière HTTPS. La base pédagogique est `NETLAB_EDUCATION_DB` (par défaut `.netlab-data/education.sqlite3`).

L’enseignant peut créer des comptes étudiants, des groupes, ajouter des élèves, partager un instantané de la topologie courante et consulter les statuts de remise. Chaque élève dispose d’une copie JSON personnelle qu’il peut modifier, sauvegarder et remettre. Les routes historiques de contrôle et le WebSocket de terminal exigent un rôle enseignant ; une copie d’élève n’est pas déployable et ne donne aucun accès au moteur Docker. L’exécution isolée par étudiant, les invitations par lien, la réinitialisation des mots de passe, la gestion fine des rôles, les quotas et PostgreSQL restent hors périmètre.

Les endpoints pédagogiques sont sous `/api/education/` : gestion de `/users` et `/groups`, affectations par groupe, `/my-assignments` côté étudiant et `/groups/<id>/submissions` côté enseignant. Les appels d’écriture authentifiés doivent inclure `X-Netlab-CSRF` avec la valeur du cookie `netlab_csrf`.

## Étape 8 — premier catalogue de services

L’endpoint enseignant authentifié `GET /api/services` retourne les profils avec catégorie, image, commande, ports, ressources, variables requises et contraintes. `nginx` (`nginx:stable-alpine`) et `apache` (`httpd:2.4-alpine`) sont les seuls profils catalogue immédiatement déployables. Le validateur refuse l’utilisation d’un profil planifié et refuse qu’un nœud de catalogue remplace son image ou sa commande attendue. Les topologies historiques v1 sans `service_id` restent compatibles ; l’ajout historique de nœuds Docker personnalisés sans profil catalogue demeure possible et reçoit les limites génériques.

L’ajout d’un profil web peut définir `published_port` en plus de `service_id`. Docker publie alors le port du conteneur sur `127.0.0.1:<published_port>` uniquement ; aucun port n’est exposé sur le réseau externe par défaut. Une vérification Docker avec un port déjà pris échouera au lancement. Chaque nœud reçoit aussi des limites Docker (`--memory`, `--cpus`, `--pids-limit`) ; aucun lancement de conteneur n’a été effectué dans le cadre de cette étape.

Les profils de bases de données, DNS/DHCP, WordPress, CI/CD et Laravel sont de la documentation/catalogue seulement. Ils ne deviennent pas exécutables tant que le prototype ne gère pas leurs secrets, configurations, volumes persistants, exigences réseau et ressources. Les appliances pfSense/MikroTik/Windows demandent une architecture VM/KVM et une validation de licences ; elles ne sont pas des images Docker activables ici. Le réseau bridge demeure partagé et les liaisons visuelles n’implémentent pas encore des segments isolés.
