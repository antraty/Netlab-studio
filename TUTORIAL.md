# Guide complet de Netlab Studio

Ce guide présente l’objectif du projet, son fonctionnement, les rôles disponibles et les parcours principaux. Netlab Studio est encore un **prototype** : les fonctions décrites comme disponibles ci-dessous sont celles de l’implémentation actuelle, pas toutes les ambitions du README.

## 1. Qu’est-ce que Netlab Studio ?

Netlab Studio permet de concevoir des topologies de laboratoire réseau dans un navigateur, puis d’exécuter leurs machines et services comme de vrais conteneurs Docker. À la différence d’un simulateur, les commandes et tests réseau sont exécutés dans les environnements du laboratoire.

Exemple :

```text
Client Ubuntu ── LAN A ── Routeur Linux ── LAN B ── Serveur Debian
```

Le client, le routeur et le serveur sont des conteneurs réels. Les segments Docker, adresses IPv4 et routes statiques peuvent être configurés pour tester une communication réelle, par exemple avec `ping`.

### Ce que le projet n’est pas encore

- Ce n’est pas encore un service cloud public ou une plateforme HA prête pour la production.
- Le backend KVM/libvirt est préparé mais bloqué : les VM Windows, pfSense, MikroTik et Active Directory ne sont pas provisionnées.
- Les profils marqués « prévu » ou « étude » dans le catalogue ne sont pas déployables.
- L’éditeur, les terminaux et la supervision restent ceux d’un prototype ; la disponibilité dépend du serveur Docker utilisé.

## 2. Comment les composants fonctionnent ensemble

Dans le profil local Docker Compose, le flux est le suivant :

```text
Navigateur
   │
   ▼
Frontend Vue servi par Nginx
   │ API HTTP / WebSocket
   ▼
API FastAPI ───────── PostgreSQL
   │ jobs d’exécution
   ▼
Worker Docker ─────── Docker Engine
```

- **Frontend Vue** : éditeur visuel, écrans d’authentification, espaces enseignant et étudiant.
- **API FastAPI** : authentification, autorisations, topologies, groupes, affectations et orchestration.
- **PostgreSQL sous Compose** : persistance du profil Docker local. Le développement direct peut utiliser SQLite.
- **Worker Docker** : exécute les opérations sur les conteneurs. C’est le seul service Compose qui reçoit le socket Docker.
- **Docker Engine** : crée les conteneurs, réseaux et volumes des laboratoires.

Une topologie est la définition souhaitée d’un laboratoire. Les conteneurs et réseaux sont les ressources réelles créées par le moteur au déploiement.

## 3. Installation et démarrage local

### Prérequis

- Docker Engine et le plugin `docker compose` ;
- accès aux registres d’images Docker ;
- assez de mémoire pour les services de la plateforme et les laboratoires ;
- un navigateur moderne.

### Démarrer avec Compose

À partir de la racine du dépôt :

```bash
make setup
make up
make ps
```

`make setup` crée `.env` avec des secrets aléatoires si le fichier n’existe pas ; il ne remplace jamais une configuration existante. `make up` construit les images Linux de laboratoire puis démarre la pile. L’interface est disponible à l’adresse `http://localhost:8080`.

Vérifier la santé de l’application :

```bash
curl -fsS http://localhost:8080/health
curl -fsS http://localhost:8080/ready
```

Un résultat prêt doit notamment indiquer que la base et le worker sont joignables. Pour voir les journaux :

```bash
make logs
```

Arrêter les services sans supprimer les données :

```bash
docker compose down
```

**Attention :** `docker compose down -v` supprime aussi les volumes persistants, notamment les données PostgreSQL et les volumes des laboratoires.

### Premier compte enseignant

1. Ouvrir `http://localhost:8080`.
2. Saisir le jeton `NETLAB_BOOTSTRAP_TOKEN` du fichier `.env`.
3. Créer le nom, l’adresse e-mail et le mot de passe du premier compte.
4. Se connecter ensuite avec l’adresse e-mail et le mot de passe créés.

Le jeton sert uniquement à créer le premier compte. Il ne remplace pas le mot de passe et il n’existe pas d’inscription publique.

**Sécurité :** un jeton de bootstrap a été montré dans la conversation qui a précédé ce guide. S’il n’a pas encore servi, remplacez sa valeur dans `.env` par un nouveau secret aléatoire avant de créer le compte, puis recréez le service de contrôle :

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# Copier localement la sortie dans NETLAB_BOOTSTRAP_TOKEN de .env.
docker compose up -d --force-recreate control
```

Ne partagez pas la sortie, le fichier `.env` ou une capture qui le contient. Une fois le premier compte créé, le bootstrap ne permet pas de créer un second compte initial.

### Lancement développeur sans Compose

Le dépôt décrit également un lancement direct avec Uvicorn et Vite ; voir le README pour les commandes détaillées. Dans ce mode, `NETLAB_WORKER_URL` peut pointer vers `http://127.0.0.1:9000`. À l’inverse, dans Compose, les services doivent se parler avec leurs noms DNS (`worker` et `control`) : `127.0.0.1` désignerait le conteneur lui-même.

## 4. Les rôles et les permissions

### Administrateur (`admin`)

- Accède aux fonctions d’enseignant.
- Peut inviter des enseignants et administrer les fonctions réservées à l’administration.
- Peut aussi disposer de laboratoires et participer aux activités pédagogiques.

### Enseignant (`teacher`)

- Crée et gère ses laboratoires.
- Crée des comptes étudiants ou invite des étudiants.
- Crée des groupes, y ajoute des étudiants et affecte des travaux pratiques.
- Consulte les remises, attribue une note et fournit un commentaire.
- Partage un laboratoire avec un autre compte enseignant en rôle `editor` ou `viewer`.

### Étudiant (`student`)

- Consulte les travaux qui lui sont affectés.
- Crée sa copie personnelle à partir du laboratoire affecté.
- Modifie les paramètres réseau autorisés, sauvegarde, déploie, vérifie et arrête sa copie.
- Utilise les commandes de terminal autorisées sur sa copie.
- Remet son travail et consulte l’historique, les notes et les retours.

### Rôles d’accès à un laboratoire partagé

- **Owner / propriétaire** : contrôle le laboratoire et peut gérer ses membres.
- **Editor / éditeur** : peut modifier le laboratoire et agir sur son runtime.
- **Viewer / lecteur** : accès en lecture seule.

Le rôle de compte et le rôle de membre sont distincts : être enseignant ne rend pas automatiquement propriétaire de tous les laboratoires.

## 5. Parcours enseignant : créer et exécuter un laboratoire

1. **Créer un laboratoire** depuis l’espace enseignant.
2. Choisir un modèle ou partir de la topologie affichée.
3. **Ajouter des nœuds** avec un profil du catalogue ou créer un nœud personnalisé.
4. Organiser les nœuds sur le canevas. Utiliser **Relier** pour dessiner les liens.
5. Pour une topologie v2, configurer séparément :
   - les segments réseau et leurs CIDR ;
   - les interfaces de chaque nœud ;
   - les adresses IPv4 et passerelles ;
   - les routes statiques ;
   - le mode routeur si le forwarding IPv4 est nécessaire.
6. Choisir les nœuds source et destination du test de connectivité.
7. Corriger les erreurs indiquées par la validation locale ; le serveur valide également les topologies à la sauvegarde et au déploiement.
8. Cliquer **Nouvelle version** pour sauvegarder une version de la topologie.
9. Cliquer **Déployer**, puis **Tester la connectivité**.
10. Sélectionner un nœud pour ouvrir son terminal et examiner les journaux et états.
11. Cliquer **Arrêter** lorsque le laboratoire n’est plus utilisé.

Les modifications non sauvegardées sont signalées. L’éditeur inclut **Annuler** (`Ctrl/Cmd+Z`) et **Rétablir** (`Ctrl/Cmd+Maj+Z`) pour les actions couvertes.

### Liens et segments réseau

Les traits du canevas représentent les liens de la topologie. Les réseaux Docker effectifs d’une topologie v2 sont définis par les segments et les interfaces réseau des nœuds. Pour assurer la connectivité réelle, configurez ces interfaces ; ne vous fiez pas uniquement au trait graphique.

### Versions, clonage, import et export

- **Nouvelle version** conserve un instantané immuable de la topologie.
- **Restaurer** remplace la topologie courante par une version choisie.
- **Cloner** crée un nouveau laboratoire indépendant.
- **Exporter** télécharge une définition JSON portable.
- **Importer** crée un nouveau laboratoire depuis un JSON compatible.

Le JSON décrit la configuration, pas une image VM complète ni une sauvegarde universelle des fichiers de tous les conteneurs.

## 6. Catalogue de services

Les profils dont le statut est **disponible** peuvent être ajoutés depuis le catalogue. Le catalogue actuel comprend notamment Nginx, Apache, CoreDNS, PostgreSQL, MySQL et MongoDB. Les profils de bases de données peuvent utiliser des volumes persistants et des références à des secrets.

Les services **prévus** ou **à l’étude** sont informatifs : ils ne deviennent pas opérationnels simplement en les sélectionnant dans le catalogue. DHCP/dnsmasq, GitLab, Jenkins, WordPress, Laravel et les appliances/VM restent soumis à des intégrations ou à des travaux ultérieurs.

### Secrets des services

Ne placez jamais un mot de passe dans la topologie ou dans un fichier versionné. La topologie doit contenir une référence de secret, par exemple :

```json
{
  "secret_refs": {
    "POSTGRES_PASSWORD": "lab-password"
  }
}
```

Le worker doit recevoir la variable correspondante (`NETLAB_SECRET_LAB_PASSWORD`) depuis son environnement ou le gestionnaire de secrets utilisé pour le déploiement. Les références ne sont pas les valeurs elles-mêmes.

## 7. Parcours enseignant : affecter un TP

1. Dans **Partage pédagogique**, créer un groupe.
2. Créer un compte étudiant ou lui envoyer une invitation à usage unique.
3. Ajouter les étudiants au groupe.
4. Choisir le groupe et le modèle (topologie courante ou modèle disponible).
5. Renseigner un titre, des consignes et des critères de réussite, un par ligne.
6. Cliquer **Affecter au groupe**.
7. Consulter les remises du groupe et ouvrir l’historique d’un étudiant.
8. Évaluer une tentative avec une note sur 100 et un commentaire.

La topologie affectée est un instantané : les modifications ultérieures du laboratoire source ne changent pas les copies des étudiants.

Sans système d’e-mail configuré, le jeton d’invitation ou de réinitialisation doit être transmis manuellement par un canal séparé et sûr. Les jetons sont à usage unique et expirent.

## 8. Parcours étudiant : réaliser et remettre un TP

1. Se connecter avec le compte fourni ou accepter l’invitation et définir son mot de passe.
2. Ouvrir **Mes travaux pratiques** puis choisir une affectation.
3. Cliquer **Créer ma copie**. La copie possède son propre identifiant et son runtime séparé.
4. Sélectionner les nœuds et configurer les adresses IPv4, passerelles et routes disponibles.
5. Enregistrer la copie.
6. Cliquer **Déployer ma copie**, puis vérifier la connectivité.
7. Utiliser le terminal de sa copie pour les commandes autorisées et consulter les résultats.
8. Arrêter le runtime puis cliquer **Remettre**.
9. Revenir plus tard pour consulter la note et le retour enseignant.

**Réinitialiser ma copie** restaure le modèle initial après nettoyage du runtime. Cela ne supprime pas l’historique des remises précédentes. Les quotas et délais de vie du runtime s’appliquent aussi aux copies étudiantes.

## 9. Terminaux, état et supervision

- Le terminal WebSocket enseignant donne accès au nœud sélectionné lorsque l’exécution est disponible.
- Pour l’usage ponctuel restreint, les commandes autorisées sont `hostname`, `uname`, `ip` et `ping` ; les formes acceptées sont limitées par le serveur.
- Le terminal étudiant est limité à la copie personnelle et à un jeu de commandes contrôlé.
- Les vues de supervision enseignantes/admin présentent l’inventaire Docker et certaines mesures de ressources lorsqu’elles sont disponibles.
- `/health` indique que l’API répond ; `/ready` vérifie également la base et le worker configuré.

Les mesures Docker ne sont pas un système complet de métriques historisées. Le détail dépend du moteur Docker et du worker.

## 10. Sécurité et bonnes pratiques

- Garder `.env` privé ; il contient des secrets et est ignoré par Git.
- Ne jamais publier le socket Docker, le port du worker ou le port PostgreSQL sur Internet.
- Ne pas utiliser le profil local Compose comme déploiement cloud de production.
- Le mode production exige des paramètres TLS, des origines et hôtes autorisés, des images explicitement autorisées et mTLS entre le plan de contrôle et les workers.
- Monter les certificats depuis un gestionnaire de secrets ou des fichiers protégés, sans les commettre.
- Utiliser des images vérifiées et épinglées avant tout déploiement partagé.
- Arrêter les laboratoires inutilisés ; ils consomment les ressources de l’hôte.
- Faire des sauvegardes avant migration ou modification majeure.

L’application reste un prototype et ne fournit pas encore une HA complète, un système de sauvegarde géré, un broker externe, un moteur multi-hyperviseur ou une certification de sécurité.

## 11. Dépannage rapide

### Le frontend ne démarre pas, le contrôle est unhealthy

```bash
docker compose ps
docker compose logs --tail=100 control worker db
curl -i http://localhost:8080/ready
```

Dans Compose, le contrôle doit joindre `http://worker:9000`, pas `127.0.0.1:9000`. La documentation [DEPLOYMENT.md](./DEPLOYMENT.md) explique la séparation entre les URL de lancement sur l’hôte et celles du réseau Compose.

### Le bootstrap ne fonctionne pas

- Vérifier qu’aucun utilisateur n’a déjà été créé.
- Vérifier que le jeton entré correspond à `NETLAB_BOOTSTRAP_TOKEN` dans le conteneur de contrôle.
- Après un changement dans `.env`, recréer le service `control` avec `docker compose up -d --force-recreate control`.
- Ne pas supprimer les volumes pour contourner un problème de connexion.

### Le déploiement d’un laboratoire échoue

- Valider la topologie et lire le message d’erreur dans l’interface et `docker compose logs worker`.
- Vérifier que les images de laboratoire nécessaires sont construites ou téléchargeables.
- Vérifier que chaque interface référence un segment existant et que les sous-réseaux ne se chevauchent pas.
- Vérifier l’espace disque, la mémoire et le fonctionnement du Docker Engine.

### Le terminal ne se connecte pas

- Vérifier que le laboratoire est déployé et que le nœud est actif.
- Vérifier que le proxy autorise les WebSockets (`/ws/`).
- Lire les journaux du contrôle et du worker ; ne pas exposer directement le socket Docker au navigateur.

## 12. Glossaire

| Terme | Signification |
|---|---|
| Laboratoire | Ensemble persistant de configuration, nœuds, réseaux et versions. |
| Topologie | Description JSON des nœuds, réseaux, interfaces, liens et vérifications. |
| Nœud | Conteneur/service d’un laboratoire dans le backend Docker actuel. |
| Segment | Réseau Docker partagé par les interfaces qui y sont connectées. |
| Route statique | Route IPv4 appliquée dans un conteneur au déploiement. |
| Worker | Service qui exécute les opérations sur le moteur Docker. |
| Affectation | TP publié par un enseignant à un groupe. |
| Copie étudiante | Topologie et runtime propres à un étudiant et à une affectation. |
| Lease | Bail temporaire d’un job pris en charge par un worker ; il peut expirer et être repris. |

## Documentation associée

- [README.md](./README.md) : vision, roadmap et état des fonctionnalités.
- [DEPLOYMENT.md](./DEPLOYMENT.md) : installation Compose, migration PostgreSQL et configuration mTLS.
- [images/README.md](./images/README.md) : images de laboratoire contrôlées.
