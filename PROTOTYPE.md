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

## Étape 2 — laboratoire utilisable

Le serveur de contrôle local et l’interface web sont disponibles dans `server.py` et `web/` :

```bash
python3 server.py --topology topology.json
# ouvrir http://127.0.0.1:8080
```

L’interface permet de charger la topologie, de déployer ou arrêter le laboratoire, de lancer le test de connectivité, d’afficher l’état des nœuds et les événements, puis d’enregistrer la topologie. Un terminal par nœud accepte uniquement les commandes de diagnostic `hostname`, `uname`, `ip` et `ping` afin d’éviter d’exposer un shell arbitraire dans ce prototype.

L’API HTTP expose les routes suivantes :

- `GET /api/topology`, `POST /api/topology` ;
- `GET /api/status` et `GET /api/logs` ;
- `POST /api/up`, `/api/verify` et `/api/down` ;
- `POST /api/nodes/<nom>/terminal`.

Cette interface est volontairement locale et ne fournit pas encore d’authentification. Elle ne doit pas être exposée sur un réseau public avant l’ajout de l’isolation, des contrôles d’accès et des limites de ressources prévus par le projet.

## Début de l’étape 2 — séparation du contrôle et de l’exécution

Le serveur HTTP joue le rôle de plan de contrôle et délègue désormais les opérations à `DockerOrchestrator` dans `orchestrator.py`. Cette frontière permet de conserver la même API lorsqu’un moteur distant, une exécution sur VM ou un autre adaptateur sera ajouté. Le navigateur ne parle donc pas directement au CLI Docker.
