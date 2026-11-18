# Netlab Studio

> **Packet Tracer + Docker + Cloud** : une plateforme de laboratoires réseau réels, accessible depuis un navigateur.

## Vision

Netlab Studio est une plateforme qui permet de **dessiner, déployer et utiliser des laboratoires réseau et système réels depuis un navigateur**.

L’idée principale est de conserver la simplicité d’un outil de topologie comme Cisco Packet Tracer, tout en remplaçant la simulation par de vrais environnements exécutés à la demande dans Docker et, lorsque nécessaire, dans des machines virtuelles.

L’utilisateur dessine une topologie — par exemple :

```text
PC Ubuntu ─── Switch virtuel ─── Routeur
                    │
             Serveur Debian
```

Puis il clique sur **Déployer**. Netlab Studio crée les machines, configure les réseaux virtuels et démarre les services nécessaires dans un environnement isolé. L’utilisateur peut ensuite ouvrir un terminal sur chaque machine, configurer les adresses IP, lancer de vrais services et effectuer de vrais tests réseau.

L’objectif n’est donc pas de simuler un réseau, mais de fournir un **laboratoire fonctionnel, reproductible et partageable**, dans lequel un `ping`, un serveur web, un service DNS ou une application produisent des résultats réels.

## L’idée en une phrase

L’utilisateur dessine sa topologie, clique sur **Déployer**, puis obtient automatiquement un environnement complet — conteneurs, machines virtuelles, réseaux virtuels et services — accessible depuis des terminaux dans le navigateur.

Le projet doit rendre possible un laboratoire tel que celui-ci :

```text
Client Ubuntu (Docker) ─── Réseau virtuel ─── Serveur Debian (Docker)
                                      │
                              Pare-feu pfSense (VM)
```

Dans une version plus avancée, le même principe permettra de sélectionner un modèle comme **laboratoire Active Directory** et de provisionner automatiquement les machines et services nécessaires, sous réserve des capacités de l’infrastructure et des licences.

## Le problème

Les outils de simulation réseau sont très utiles pour apprendre les concepts et les commandes, mais ils ne reproduisent pas toujours le comportement de véritables systèmes d’exploitation et de véritables services.

Pour mettre en place un laboratoire réel, il faut souvent :

- installer et configurer plusieurs logiciels ;
- gérer des machines virtuelles et des réseaux virtuels ;
- résoudre des problèmes de compatibilité ;
- disposer d’un ordinateur suffisamment puissant ;
- reconstruire manuellement le même environnement pour chaque étudiant.

Netlab Studio cherche à rendre cette expérience plus simple, plus accessible et plus reproductible.

## Positionnement : plus qu’un simulateur

Netlab Studio s’inspire de l’expérience de création de topologies de Cisco Packet Tracer, mais avec une différence fondamentale : **les nœuds du laboratoire exécutent de vrais environnements**.

| Simulateur réseau classique | Netlab Studio |
| --- | --- |
| Topologie simulée | Environnement réseau réellement déployé |
| Équipements et commandes simulés | Conteneurs, machines virtuelles et commandes réelles |
| Principalement orienté équipements Cisco | Linux, Windows, Docker, pfSense, MikroTik et autres systèmes selon les intégrations |
| Services limités ou simulés | Apache, Nginx, DNS, DHCP, MySQL, GitLab, Jenkins, etc. |
| Pas de déploiement applicatif généraliste | Déploiement possible de services et d’applications selon les images disponibles |
| Installation locale nécessaire | Accès depuis un navigateur |
| Laboratoire souvent recréé manuellement | Laboratoire exportable, partageable et reproductible |

Le positionnement de Netlab Studio peut se résumer ainsi :

> **La simplicité d’un outil de topologie, avec la puissance d’un véritable environnement Docker/VM dans le cloud.**

### Ce qui distingue Netlab Studio

Netlab Studio ne cherche pas à reproduire uniquement les commandes d’un équipement réseau. Sa valeur est de provisionner un environnement complet et de le rendre utilisable immédiatement :

- **déploiement en un clic** d’un scénario ou d’un modèle de laboratoire ;
- **systèmes et commandes réels**, et non des équipements simulés ;
- **accès depuis un navigateur**, sans installation d’un simulateur sur chaque poste ;
- **laboratoires partageables et reproductibles**, notamment pour les enseignants et les étudiants ;
- **services applicatifs réels** comme Apache, Nginx, GitLab, Jenkins, MySQL, PostgreSQL, MongoDB, WordPress ou Laravel ;
- **supervision en temps réel** des utilisateurs, conteneurs, ressources et erreurs ;
- à terme, **assistance intelligente** capable d’analyser la topologie et de proposer des pistes de diagnostic explicables.

Le navigateur est l’interface d’accès ; le plan d’exécution peut être hébergé sur une infrastructure distante afin que l’utilisateur n’ait pas à installer Docker ou les machines virtuelles localement.

## Expérience utilisateur cible

1. L’utilisateur crée un laboratoire ou choisit un modèle existant.
2. Il ajoute des machines, des équipements et des services.
3. Il relie les nœuds avec des interfaces et des réseaux virtuels.
4. Il configure les paramètres nécessaires : image, ressources, adresses IP, VLAN, routes et variables d’environnement.
5. Il clique sur **Déployer**.
6. Netlab Studio provisionne l’environnement automatiquement.
7. L’utilisateur ouvre un terminal ou une console directement dans le navigateur.
8. Il réalise son TP, teste la connectivité et observe le comportement réel du laboratoire.
9. Il peut arrêter, redémarrer, cloner, exporter ou partager le laboratoire.

Exemple de test dans un laboratoire déployé :

```bash
ping 192.168.1.10
```

Le résultat provient d’une vraie communication entre systèmes du laboratoire, et non d’une simulation graphique.

## Fonctionnalités envisagées

### 1. Éditeur de topologie

- Ajouter et supprimer des nœuds.
- Relier les interfaces par des câbles ou des liens virtuels.
- Organiser visuellement le laboratoire.
- Afficher l’état des nœuds et des connexions.
- Sauvegarder la topologie sous une forme portable et versionnable.

### 2. Déploiement automatisé

À partir de la topologie, la plateforme doit pouvoir :

- créer les conteneurs et, à terme, les machines virtuelles ;
- créer les réseaux virtuels ;
- connecter les interfaces ;
- appliquer une configuration initiale ;
- démarrer ou arrêter les services ;
- signaler les erreurs de déploiement de manière compréhensible.

### 3. Machines et services réels

Les premiers laboratoires peuvent s’appuyer sur des conteneurs Linux. La plateforme pourra ensuite intégrer d’autres environnements, selon les contraintes techniques et de licence :

- Ubuntu, Debian et autres distributions Linux ;
- serveurs web Apache et Nginx ;
- DNS et DHCP ;
- MySQL, PostgreSQL et MongoDB ;
- GitLab et Jenkins ;
- WordPress et applications web ;
- pare-feu et appliances réseau ;
- machines virtuelles Windows ou pfSense lorsque l’infrastructure le permet.

### 4. Terminal et consoles dans le navigateur

Chaque machine doit pouvoir être utilisée directement depuis l’interface :

- terminal web ;
- affichage des journaux ;
- état du processus et du réseau ;
- accès aux fichiers ou à une console selon le type de nœud ;
- indication claire de l’état : en préparation, actif, arrêté ou en erreur.

### 5. Modèles de laboratoires

Un utilisateur doit pouvoir créer un laboratoire à partir d’un modèle prêt à l’emploi, par exemple :

- introduction aux réseaux IP ;
- routage statique ;
- VLAN et inter-VLAN ;
- DNS et DHCP ;
- serveur web et base de données ;
- administration Linux ;
- CI/CD avec GitLab et Jenkins ;
- laboratoire Active Directory, lorsque les machines virtuelles nécessaires seront prises en charge.

### 6. Partage et reproductibilité

Un enseignant ou un administrateur peut préparer un laboratoire puis le partager avec un groupe :

- import d’un laboratoire depuis un fichier ou un lien ;
- déploiement identique pour chaque participant ;
- versionnement des modifications ;
- duplication d’un laboratoire sans modifier l’original ;
- possibilité de remettre un environnement dans son état initial.

### 7. Supervision

Pour les laboratoires actifs, la plateforme pourra afficher :

- les utilisateurs connectés ;
- les nœuds et conteneurs en cours d’exécution ;
- l’utilisation CPU et mémoire ;
- les journaux importants ;
- les erreurs de réseau ou de démarrage ;
- la consommation de ressources par laboratoire.

### 8. Assistance intelligente

Une fonctionnalité d’assistance pourra analyser la topologie et les événements du laboratoire afin de fournir des pistes de diagnostic, par exemple :

> « Le serveur DHCP est inaccessible. Vérifiez la connexion au VLAN 20. »

ou :

> « Cette machine ne possède pas de passerelle par défaut. »

Cette assistance doit expliquer les raisons possibles et proposer des vérifications, sans masquer le fonctionnement réel du réseau ni remplacer l’apprentissage.

## MVP proposé

La première version doit rester volontairement ciblée. Elle pourrait inclure :

- un éditeur visuel de topologie simple ;
- des nœuds Linux basés sur Docker ;
- deux ou trois types de réseaux virtuels ;
- la création et la suppression de liens ;
- le déploiement et l’arrêt d’un laboratoire ;
- un terminal web par nœud ;
- un test de connectivité réel entre conteneurs ;
- la sauvegarde et le chargement d’un laboratoire ;
- une documentation de démarrage.

Un premier scénario de démonstration pertinent serait :

```text
Client Ubuntu ─── Réseau virtuel ─── Serveur Debian
```

L’utilisateur doit pouvoir déployer ce scénario, ouvrir les deux terminaux, configurer les adresses IP et vérifier la connectivité avec `ping`.

## Architecture envisagée

L’architecture exacte sera définie pendant la conception, mais le projet peut être organisé autour des composants suivants :

- **Interface web** : édition de la topologie, gestion des laboratoires et accès aux consoles.
- **API de contrôle** : création, lecture, modification et suppression des laboratoires et de leurs nœuds.
- **Orchestrateur** : traduction d’une topologie en ressources déployables.
- **Moteur d’exécution** : Docker en première étape, puis prise en charge éventuelle de machines virtuelles.
- **Gestion réseau** : création des réseaux, des interfaces, des routes et des règles d’isolement.
- **Stockage** : métadonnées, configurations, modèles, journaux et états des laboratoires.
- **WebSocket ou mécanisme temps réel** : terminal web, logs et actualisation des états.

La plateforme devra séparer clairement le plan de contrôle — qui décrit et administre les laboratoires — du plan d’exécution — qui fait tourner les environnements réels.

## Stack cible et structure du projet

La migration vers une stack structurée commence maintenant. Le backend cible utilise **FastAPI + Pydantic** pour le plan de contrôle et le frontend utilise **Vue 3 + TypeScript + Vite** pour l’éditeur. `orchestrator.py` reste indépendant du transport HTTP afin de pouvoir remplacer Docker local par un worker Docker distant ou un moteur de machines virtuelles.

```text
netlab-studio/
├── backend/
│   ├── app/
│   │   ├── main.py           # application FastAPI et routes de contrôle
│   │   ├── models.py         # contrats Pydantic des topologies
│   │   ├── storage.py        # versions, restauration, clonage et export
│   │   └── terminal.py       # sessions shell Docker via WebSocket
│   └── requirements.txt      # FastAPI, Uvicorn et Pydantic
├── worker/
│   ├── main.py               # service d’exécution Docker séparé
│   ├── contracts.py          # contrat de jobs control-plane/worker
│   └── requirements.txt      # dépendances du worker
├── frontend/
│   ├── src/
│   │   ├── App.vue           # écran du laboratoire et éditeur
│   │   ├── api.ts            # client HTTP typé
│   │   ├── types.ts          # types TypeScript partagés côté UI
│   │   └── style.css         # interface console de laboratoire
│   ├── package.json          # Vue 3, TypeScript et Vite
│   └── vite.config.ts        # proxy de développement vers FastAPI
├── orchestrator.py           # adaptateurs Docker local et worker distant
├── images/                   # images de laboratoire avec outils réseau
├── .netlab-data/             # versions locales ignorées par Git
├── topology.json             # scénario Ubuntu/Debian versionné
└── netlab.py                 # primitives Docker et compatibilité CLI
```

### Démarrage de la stack migrée

Dans un terminal, installer puis démarrer l’API. Le premier démarrage nécessite un jeton de configuration aléatoire ; il ne sert qu’à créer le premier compte enseignant :

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
export NETLAB_BOOTSTRAP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn backend.app.main:app --reload --port 8000
```

Dans un second terminal, installer puis démarrer Vue :

```bash
cd frontend
npm install
npm run dev
```

Ouvrir ensuite `http://127.0.0.1:5173`. La page de configuration demande le jeton et crée le premier enseignant ; l’application ne propose pas d’inscription publique. Conserver ce jeton hors du dépôt et de l’historique shell, puis le supprimer de l’environnement après la création du compte. Les comptes étudiants sont créés par un enseignant avec un mot de passe initial, à transmettre séparément. L’API FastAPI est disponible sur `http://127.0.0.1:8000`, avec sa documentation OpenAPI sur `/docs` et son contrôle de santé sur `/health`.

La migration FastAPI/Vue est maintenant la base active du projet. Le terminal WebSocket et la persistance versionnée locale sont disponibles en prototype. L’étape 6 ajoute la séparation entre le plan de contrôle et le worker Docker : lorsque `NETLAB_WORKER_URL` est défini, FastAPI envoie des jobs HTTP authentifiés au worker au lieu d’accéder au moteur Docker localement. Les fichiers `.netlab-data/` décrivent la définition souhaitée des laboratoires ; l’état temporaire des conteneurs reste géré par le worker.

### Phase 1 — vrai laboratoire multi-réseaux

Le moteur Docker prend en charge le format de topologie v2. Une topologie v2 déclare plusieurs segments Docker, les interfaces de chaque nœud, leurs adresses IPv4 et leurs routes statiques. Le scénario `topology.json` déploie réellement :

```text
Client Ubuntu 10.0.1.10/24 ── LAN A ── Router Linux ── LAN B ── Server Debian 10.0.2.10/24
                                      10.0.1.1       10.0.2.1
```

Le routeur reçoit `NET_ADMIN` et `net.ipv4.ip_forward=1`. Le client et le serveur reçoivent les routes nécessaires pour tester un trafic inter-réseaux réel. Les topologies v1 restent compatibles, mais utilisent un seul réseau Docker partagé.

Construire d’abord les images contrôlées de laboratoire :

```bash
docker build -t netlab/ubuntu-lab:24.04 images/ubuntu-lab
docker build -t netlab/debian-lab:bookworm images/debian-lab
docker build -t netlab/debian-router:bookworm images/debian-router
```

Puis déployer et tester le scénario :

```bash
python3 netlab.py topology.json validate
python3 netlab.py topology.json up
python3 netlab.py topology.json verify
python3 netlab.py topology.json down
```

`up` crée un réseau Docker par segment, attribue les IP déclarées, connecte les interfaces supplémentaires et applique les routes. En cas d’échec, les conteneurs et réseaux créés pendant la tentative sont nettoyés.

### Démarrer le worker séparé en développement

Terminal 1 — worker Docker :

```bash
export NETLAB_WORKER_TOKEN=local-development-token
uvicorn worker.main:app --host 127.0.0.1 --port 9000
```

Terminal 2 — API de contrôle :

```bash
export NETLAB_WORKER_URL=http://127.0.0.1:9000
export NETLAB_WORKER_TOKEN=local-development-token
uvicorn backend.app.main:app --reload --port 8000
```

Le worker doit rester sur un réseau privé ou localhost : le token est une première barrière de développement, pas encore une solution cloud complète. Il refuse maintenant les jobs lorsque `NETLAB_WORKER_TOKEN` n’est pas configuré ; définissez une valeur forte et identique sur l’API et le worker. La prochaine évolution ajoutera une file de tâches, des identités de worker, des quotas et un transport mTLS.

### Étape 7 — comptes et partage pédagogique (prototype local)

Le prototype inclut désormais des comptes enseignants/étudiants, des sessions locales stockées sous forme de hachages, un cookie de session `HttpOnly`, une protection CSRF, des groupes, l’affectation d’un instantané de topologie à un groupe, une copie JSON personnelle par étudiant et le suivi des remises. La base SQLite est locale dans `.netlab-data/education.sqlite3` (ou `NETLAB_EDUCATION_DB`) ; sauvegardez-la avec les données pédagogiques.

Les étudiants peuvent éditer/sauvegarder leur copie JSON et la remettre à l’enseignant. Ils ne peuvent pas appeler les routes du plan de contrôle Docker ni ouvrir le terminal WebSocket. **Les copies étudiantes ne sont pas encore exécutables** : il n’existe toujours pas d’isolation de conteneurs par étudiant ni de stockage multi-utilisateur cloud. Les enseignants, eux, pilotent toujours le laboratoire local unique du prototype.

Cette authentification est une première protection pour le prototype local, pas une certification ni un feu vert pour une exposition publique. Avant une mise en service, il faudra notamment HTTPS, un secret de session robuste, une politique de sauvegarde/récupération, une limitation des tentatives de connexion, un déploiement isolé du worker, des quotas, une séparation des ressources par laboratoire et une revue de sécurité.

## Sécurité et isolation

L’exécution de vrais systèmes implique des exigences de sécurité importantes. Le projet devra notamment prévoir :

- l’isolation entre les laboratoires et entre les utilisateurs ;
- des limites CPU, mémoire, stockage et durée d’exécution ;
- un contrôle strict des images et des privilèges ;
- la restriction des accès réseau sortants et entrants ;
- la protection des terminaux et des secrets ;
- le durcissement de l’authentification et la gestion avancée des rôles ;
- la suppression propre des ressources à la fin d’un laboratoire ;
- la traçabilité des opérations d’administration.

La sécurité ne doit pas être ajoutée après le MVP : elle fait partie du fonctionnement fondamental de la plateforme.

## Public cible

Netlab Studio peut s’adresser à plusieurs profils :

- étudiants en réseaux, systèmes et DevOps ;
- enseignants et formateurs qui préparent des travaux pratiques ;
- administrateurs systèmes et réseaux ;
- équipes qui souhaitent reproduire un environnement de test ;
- développeurs qui ont besoin de tester des services dans une topologie contrôlée.

## Principes du projet

1. **Du réel plutôt que de la simulation** : exécuter de vrais systèmes et services lorsque cela est possible.
2. **Accessible depuis le navigateur** : réduire l’installation et la configuration côté utilisateur.
3. **Reproductible** : un laboratoire doit pouvoir être sauvegardé, partagé et recréé à l’identique.
4. **Progressif** : commencer par un MVP fiable avant d’ajouter les scénarios complexes.
5. **Pédagogique** : rendre les erreurs visibles et compréhensibles.
6. **Extensible** : permettre l’ajout de nouvelles images, de nouveaux services et de nouveaux types de nœuds.
7. **Sécurisé par défaut** : isoler les laboratoires et limiter les ressources dès la conception.

## Feuille de route de développement

La progression suit une règle simple : construire d’abord un moteur réel et sécurisé, puis ajouter l’expérience Packet Tracer, le cloud, les usages pédagogiques et l’assistance intelligente.

### Étape 0 — Architecture et règles de sécurité

- Séparer le plan de contrôle du plan d’exécution.
- Stabiliser le format versionné des topologies.
- Définir les limites CPU, mémoire, stockage et durée.
- Préparer l’isolation entre utilisateurs et laboratoires.
- Contrôler les images et les privilèges autorisés.
- Prévoir l’authentification, les rôles, les logs et l’audit.

### Étape 1 — Moteur local de laboratoire

- [x] Charger une topologie JSON v1 ou v2.
- [x] Créer un réseau Docker par segment.
- [x] Lancer plusieurs conteneurs Linux et connecter leurs interfaces.
- [x] Attribuer des adresses IPv4 et appliquer des routes statiques.
- [x] Activer le forwarding sur un routeur Linux.
- [x] Vérifier une connectivité inter-réseaux réelle.
- [x] Obtenir l’état des nœuds et supprimer proprement les ressources.

Cette étape est couverte par le moteur v2 et le scénario `topology.json`. Les images contrôlées sont documentées dans [`images/README.md`](images/README.md).

### Étape 2 — API de contrôle

- Créer, lire, modifier et supprimer un laboratoire.
- Déployer, arrêter et redémarrer un laboratoire.
- Consulter l’état des nœuds et les logs.
- Garder l’API indépendante de l’interface web.
- Introduire un orchestrateur interchangeable avec Docker comme premier moteur.

### Étape 3 — Éditeur visuel de topologie

- Ajouter et déplacer des nœuds.
- Choisir une image ou un type de nœud.
- Créer et supprimer des liens.
- Configurer les noms, interfaces et paramètres réseau.
- Sauvegarder une topologie portable et versionnable.

### Étape 4 — Terminal web réel

- Ouvrir un terminal interactif par nœud.
- Afficher les logs et l’état réseau.
- Gérer les sessions et leur fermeture propre.
- Utiliser WebSocket ou un mécanisme temps réel contrôlé.
- Ne jamais exposer directement le socket Docker au navigateur.

### Étape 5 — Sauvegarde, restauration et reproductibilité

- Sauvegarder, restaurer, cloner, importer et exporter un laboratoire.
- Séparer la topologie, la configuration, l’état temporaire et les données persistantes.
- Remettre un laboratoire dans son état initial.
- Versionner les modifications.

### Étape 6 — Déploiement cloud sécurisé

- Séparer le serveur FastAPI du worker qui possède l’accès au moteur Docker.
- Exécuter les laboratoires sur une infrastructure distante.
- Isoler les laboratoires et les réseaux entre utilisateurs.
- Gérer les quotas, les expirations et la suppression automatique.
- Stocker les topologies et les données persistantes.
- Superviser l’orchestrateur et la consommation de ressources.

### Étape 7 — Utilisateurs, rôles et partage pédagogique

- Ajouter les comptes, rôles enseignant/étudiant et groupes.
- Partager un laboratoire par fichier, lien ou modèle.
- Dupliquer un laboratoire par étudiant.
- Ajouter les modèles de TP, permissions et remises à zéro.
- Suivre l’état des travaux pratiques.

### Étape 8 — Services réseau et applicatifs

- Ajouter progressivement Nginx, Apache, DNS, DHCP, MySQL, PostgreSQL, MongoDB, GitLab, Jenkins, WordPress et Laravel.
- Décrire pour chaque image ses ports, ressources, variables et contraintes.
- Étudier les appliances pfSense et MikroTik.
- Étudier Windows Server et Active Directory lorsque l’infrastructure le permettra.

#### Première tranche locale

Le catalogue `GET /api/services` décrit les images, catégories, ports, ressources, variables d’environnement et contraintes. Dans cette première tranche, seuls **Nginx** et **Apache HTTP Server** sont ajoutables/déployables depuis le catalogue. Les conteneurs ont des limites par défaut (512 Mo, 0,5 CPU et 128 processus pour ces deux profils ; 512 Mo, 1 CPU et 256 processus pour les nœuds personnalisés). Un port hôte facultatif est toujours lié à `127.0.0.1`, jamais à toutes les interfaces.

CoreDNS, DHCP/dnsmasq, PostgreSQL, MySQL, MongoDB, WordPress, Jenkins, GitLab et Laravel sont documentés dans le catalogue mais marqués **prévus** : il manque notamment le stockage persistant, la gestion des secrets, la configuration réseau adaptée ou des limites de ressources dédiées. pfSense, MikroTik CHR et Windows Server/Active Directory restent au stade d’étude VM/KVM et de vérification de licence. Les topologies v2 créent maintenant des segments Docker isolés ; l’éditeur permet aussi de configurer les sous-réseaux, interfaces, adresses IPv4, routes statiques et le mode routeur avant sauvegarde.

### Étape 9 — Supervision et observabilité

- Afficher les utilisateurs, nœuds, réseaux, logs et erreurs.
- Mesurer CPU, mémoire, stockage et trafic réseau.
- Ajouter les quotas, alertes et indicateurs d’utilisation.
- Donner aux enseignants et administrateurs une vue globale des laboratoires actifs.

#### Première tranche locale

L’endpoint enseignant `GET /api/observability` fournit un instantané global des conteneurs et réseaux Docker portant les labels Netlab, relayé aussi par le worker distant authentifié. L’interface regroupe les laboratoires actifs, comptes, nœuds, état, CPU, mémoire/limite, taille de la couche inscriptible, lectures/écritures bloc, trafic RX/TX, stockage Docker (`system df`), événements et erreurs. Les collectes sont limitées à 100 conteneurs et les métriques sont actualisées au plus toutes les 15 secondes.

Les limites CPU/mémoire/PID par conteneur de l’étape 8 restent les quotas durs disponibles. Les seuils d’alerte (CPU 80 %, mémoire 80 %, couche inscriptible 1 024 Mo par défaut) sont configurables par variables `NETLAB_ALERT_CPU_PERCENT`, `NETLAB_ALERT_MEMORY_PERCENT` et `NETLAB_ALERT_WRITABLE_STORAGE_MB`. Les métriques ne sont pas historisées, les alertes ne sont pas envoyées à l’extérieur et aucun quota agrégé par utilisateur/laboratoire n’est encore appliqué. Si le moteur Docker est indisponible, l’interface signale l’erreur au lieu d’échouer.

### Étape 10 — Assistance intelligente

- Analyser la topologie, les adresses IP, les routes, les VLAN et les logs.
- Proposer des diagnostics explicables et des commandes de vérification.
- Identifier les nœuds arrêtés, les routes manquantes et les services inaccessibles.
- Ne pas modifier silencieusement le réseau ni remplacer l’apprentissage.

## Résumé

Netlab Studio vise à réunir trois expériences dans une même plateforme :

1. **Dessiner** un réseau comme dans un outil de topologie.
2. **Déployer** de vrais systèmes et services grâce à Docker et, à terme, aux machines virtuelles.
3. **Apprendre et tester** depuis un navigateur, avec des environnements reproductibles et partageables.

Le projet commence par un laboratoire Linux minimal, mais sa vision est plus large : devenir un espace de travail réseau et système où l’on peut passer rapidement d’une idée de topologie à un environnement réel, observable et exploitable.

## Statut

Le projet est au stade du **prototype technique local**. L’idée produit et la vision long terme sont définies ; les briques couvrent désormais un laboratoire Docker multi-réseaux v2, une interface web, des comptes enseignants/étudiants, un flux élémentaire de partage pédagogique et un premier catalogue de services web. Cela ne constitue pas encore une plateforme multi-utilisateur déployable dans le cloud.

La prochaine cible est l’exécution depuis l’interface web du scénario **client Ubuntu — routeur Linux — serveur Debian**, avec deux segments, des adresses IP et du routage réel. Les laboratoires multi-services, les machines virtuelles, le partage pédagogique exécutable, la supervision et le cloud viendront ensuite.

## Prototype technique — étape 1

Le prototype exécutable est disponible dans `netlab.py`. Il accepte les topologies JSON v1 et v2. La topologie v2 de démonstration crée deux réseaux Docker, lance un client Ubuntu, un routeur Linux et un serveur Debian, configure leurs IP et routes, puis vérifie un ping inter-réseaux réel.

```bash
python3 netlab.py topology.json validate
python3 netlab.py topology.json up
python3 netlab.py topology.json verify
python3 netlab.py topology.json down
```

Voir [PROTOTYPE.md](PROTOTYPE.md) pour les prérequis, le format de topologie et les tests locaux.

Les étapes 2 et 3 sont maintenant portées par FastAPI et Vue :

```bash
export NETLAB_BOOTSTRAP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn backend.app.main:app --reload --port 8000
# dans un second terminal : cd frontend && npm run dev
```

Puis ouvrir `http://127.0.0.1:5173` pour piloter le laboratoire, consulter les états et les journaux, et éditer la topologie.

L’étape 4 ajoute une session terminal WebSocket par nœud via `ws://.../ws/nodes/<nom>/terminal`. Elle ouvre un shell dans le conteneur et transfère les entrées/sorties en continu. Elle est réservée au compte enseignant dans le prototype local. Elle n’est pas conçue pour une exposition publique ; les quotas, l’isolation cloud et une revue de sécurité restent nécessaires.

L’éditeur visuel est disponible : les nœuds peuvent être déplacés, ajoutés, supprimés ou reliés, puis sauvegardés dans la topologie JSON. Pour les topologies v2, les panneaux de configuration permettent d’ajouter ou supprimer des segments, de modifier leurs sous-réseaux, de gérer les interfaces et les routes du nœud sélectionné, puis d’activer son rôle de routeur. Deux modèles prêts à l’emploi sont proposés : un réseau local Ubuntu–Debian et un scénario de routage statique client–routeur–serveur. Le test de connectivité peut sélectionner ses nœuds et une commande contrôlée. Une validation locale signale les références, adresses et routes incohérentes et bloque la sauvegarde, le déploiement ou la vérification tant que le problème n’est pas corrigé ; le backend revalide toujours la topologie.
