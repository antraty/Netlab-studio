# Netlab Studio

> La plateforme de laboratoire réseau réel, accessible depuis un navigateur.

## Vision

Netlab Studio est une plateforme qui permet de **concevoir, déployer et utiliser des laboratoires réseau complets depuis un navigateur**.

L’utilisateur dessine une topologie — par exemple :

```text
PC Ubuntu ─── Switch virtuel ─── Routeur
                    │
             Serveur Debian
```

Puis il clique sur **Déployer**. Netlab Studio crée les machines, configure les réseaux virtuels et démarre les services nécessaires dans un environnement isolé. L’utilisateur peut ensuite ouvrir un terminal sur chaque machine, configurer les adresses IP, lancer de vrais services et effectuer de vrais tests réseau.

L’objectif n’est donc pas de simuler un réseau, mais de fournir un **laboratoire réseau fonctionnel et reproductible**.

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
| Installation locale nécessaire | Accès depuis un navigateur |
| Laboratoire souvent recréé manuellement | Laboratoire exportable, partageable et reproductible |

Le positionnement de Netlab Studio peut se résumer ainsi :

> **La simplicité d’un outil de topologie, avec la puissance d’un véritable environnement Docker/VM dans le cloud.**

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

## Sécurité et isolation

L’exécution de vrais systèmes implique des exigences de sécurité importantes. Le projet devra notamment prévoir :

- l’isolation entre les laboratoires et entre les utilisateurs ;
- des limites CPU, mémoire, stockage et durée d’exécution ;
- un contrôle strict des images et des privilèges ;
- la restriction des accès réseau sortants et entrants ;
- la protection des terminaux et des secrets ;
- l’authentification et la gestion des rôles ;
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

## Feuille de route indicative

### Étape 1 — Prototype technique

- Définir le format d’une topologie.
- Lancer deux conteneurs Linux.
- Créer un réseau virtuel entre eux.
- Vérifier la connectivité réelle.

### Étape 2 — Premier laboratoire utilisable

- Ajouter l’éditeur visuel.
- Ajouter le déploiement depuis l’interface.
- Intégrer un terminal web.
- Afficher les états et les logs.
- Sauvegarder et restaurer un laboratoire.

### Étape 3 — Expérience pédagogique

- Créer des modèles de TP.
- Ajouter le partage et la duplication.
- Ajouter les rôles enseignant/étudiant.
- Ajouter la remise à zéro d’un laboratoire.

### Étape 4 — Services et supervision

- Ajouter des images et services courants.
- Ajouter les métriques de ressources.
- Améliorer les diagnostics et les messages d’erreur.
- Étudier l’intégration de machines virtuelles et d’appliances réseau.

### Étape 5 — Assistance avancée

- Analyser la topologie et les états du laboratoire.
- Proposer des pistes de diagnostic.
- Conserver une approche explicable et utile à l’apprentissage.

## Résumé

Netlab Studio vise à réunir trois expériences dans une même plateforme :

1. **Dessiner** un réseau comme dans un outil de topologie.
2. **Déployer** de vrais systèmes et services grâce à Docker et, à terme, aux machines virtuelles.
3. **Apprendre et tester** depuis un navigateur, avec des environnements reproductibles et partageables.

Le projet commence par un laboratoire Linux minimal, mais sa vision est plus large : devenir un espace de travail réseau et système où l’on peut passer rapidement d’une idée de topologie à un environnement réel, observable et exploitable.

## Statut

Projet au stade de l’idée et du cadrage initial.

La prochaine étape est de transformer le MVP en prototype technique : **un client Ubuntu et un serveur Debian reliés dans un réseau Docker, déployables depuis une interface web et accessibles via des terminaux dans le navigateur**.

## Prototype technique — étape 1

Le premier prototype exécutable est disponible dans `netlab.py`. Il définit une topologie JSON version 1, crée un réseau Docker dédié, lance un client Ubuntu et un serveur Debian, puis vérifie leur connectivité réelle.

```bash
python3 netlab.py topology.json validate
python3 netlab.py topology.json up
python3 netlab.py topology.json verify
python3 netlab.py topology.json down
```

Voir [PROTOTYPE.md](PROTOTYPE.md) pour les prérequis, le format de topologie et les tests locaux.
