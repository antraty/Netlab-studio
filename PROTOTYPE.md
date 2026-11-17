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
uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
# ouvrir http://127.0.0.1:5173
```

L’interface permet de charger la topologie, déplacer/ajouter/supprimer/relier les nœuds, déployer ou arrêter le laboratoire, lancer le test de connectivité, afficher les états et enregistrer la topologie. Les contrats sont validés par Pydantic et l’orchestration reste dans `orchestrator.py`.

L’API HTTP expose les routes suivantes :

- `GET /api/topology`, `POST /api/topology` ;
- `GET /api/status` et `GET /api/logs` ;
- `POST /api/up`, `/api/verify` et `/api/down` ;
- `POST /api/nodes/<nom>/terminal` pour les commandes ponctuelles de compatibilité ;
- `WS /ws/nodes/<nom>/terminal` pour le terminal interactif.

Cette interface est volontairement locale et ne fournit pas encore d’authentification. Elle ne doit pas être exposée sur un réseau public avant l’ajout de l’isolation, des contrôles d’accès et des limites de ressources prévus par le projet.

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
