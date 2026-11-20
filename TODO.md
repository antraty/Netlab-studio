# Migration — FastAPI + Vue

- [x] Ajouter un profil Docker Compose reproductible avec PostgreSQL, control plane, worker Docker et frontend Nginx.
- [x] Ne monter le socket Docker que dans le worker et proxyfier l’API/ WebSocket depuis le frontend.
- [x] Ajouter les Dockerfiles, healthchecks, commandes Makefile et guide de déploiement de la stack.
- [x] Ajouter des contrats statiques de déploiement et vérifier les tests Python ainsi que le build Vue.
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
- [x] Ajouter des comptes enseignants/étudiants locaux avec hachage de mot de passe et sessions HttpOnly.
- [x] Protéger les mutations par CSRF et les endpoints d’exécution par rôle enseignant.
- [x] Ajouter groupes, membres étudiants, instantanés de laboratoires, copies JSON personnelles et suivi des remises.
- [x] Empêcher le worker Docker d’accepter des jobs lorsqu’aucun jeton n’est configuré.
- [x] Introduire un catalogue structuré décrivant les services, images, ports, ressources, variables et contraintes.
- [x] Déployer les premiers profils Nginx et Apache avec limites Docker et publication de port réservée à localhost.
- [x] Rejeter les profils non disponibles et les modifications d’image/commande d’un profil catalogue.
- [x] Documenter dans le catalogue les dépendances et limites des services et appliances restant à intégrer.
- [x] Ajouter un instantané enseignant des laboratoires, nœuds, réseaux, métriques Docker, stockage, événements et erreurs.
- [x] Afficher les usages CPU, mémoire, couche inscriptible, I/O bloc et trafic réseau avec seuils d’alerte configurables.
- [x] Relayer l’observabilité en mode worker distant et borner l’inventaire à 100 conteneurs.
- [ ] Ajouter invitations sûres, récupération/réinitialisation de mot de passe et limitation des tentatives.
- [ ] Ajouter rôles administrateur/enseignant/étudiant plus granulaires, groupes de travail et permissions par laboratoire.
- [x] Ajouter les identifiants UUID de laboratoire, rôles `owner`/`editor`/`viewer`, API d’exécution isolée par ID et sélection de plusieurs laboratoires.
- [x] Ajouter un éditeur visuel étudiant pour les interfaces IPv4, passerelles et routes statiques.
- [x] Affecter les modèles LAN et routage statique avec consignes et critères de réussite.
- [x] Historiser chaque remise avec instantané de topologie et permettre un retour enseignant par tentative.
- [x] Tester l’isolation des copies de deux étudiants, l’historique individuel et les permissions de retour enseignant.
- [x] Isoler l’exécution Docker par étudiant/affectation ; limiter déploiement, arrêt, reset, terminal et remise à la copie autorisée.
- [x] Ajouter PostgreSQL configurable et un outil de copie SQLite vers PostgreSQL pour les comptes, sessions, affectations et versions de topologie.
- [x] Appliquer des quotas de laboratoires/nœuds, CPU/mémoire/stockage par laboratoire et CPU/mémoire par utilisateur actif.
- [x] Rendre les versions immuables transactionnelles en base ; reprendre le nettoyage expiré après échec/redémarrage et coordonner les contrôleurs concurrents.
- [x] Attribuer une identité UUID stable par copie étudiante et empêcher son altération lors de la sauvegarde.
- [ ] Compléter la file de tâches, les identités de workers, mTLS et l’observabilité persistante de production.
- [ ] Historiser les métriques et définir rétention, agrégation et consultation sur la durée.
- [ ] Ajouter des notifications d’alerte et une haute disponibilité des workers de nettoyage/exécution.
- [x] Convertir les segments v2 et les interfaces déclarées en vrais réseaux Docker isolés.
- [x] Rendre le scénario de démonstration exécutable avec `getent hosts`, sans dépendre de l’installation de `ping` dans les images minimales.
- [x] Introduire la topologie v2 avec plusieurs segments Docker, interfaces IPv4 et routes statiques.
- [x] Déployer un scénario client–routeur–serveur avec forwarding IPv4 réel.
- [x] Ajouter des images Ubuntu/Debian de laboratoire contenant `ip`, `ping` et les outils réseau.
- [x] Ajouter dans l’éditeur Vue la configuration interactive des réseaux, interfaces, IP et routes v2, avec ajout/suppression contrôlée et activation du mode routeur.
- [x] Livrer l’étape 1 de l’expérience Packet Tracer : palette latérale, glisser-déposer, sélection, déplacement, suppression confirmée, zoom et panoramique du canvas.
- [x] Livrer l’étape 2 de l’expérience Packet Tracer : ports visibles, câblage entre ports, création automatique d’interfaces, segments réseau, détection des ports occupés et protection contre les câbles invalides.
- [ ] Remplacer le switch virtuel visuel par une appliance réseau réellement persistante et connectable, au-delà de l’ajout d’un simple segment Docker bridge.
- [x] Ouvrir un équipement par double-clic dans une fenêtre dédiée avec onglets terminal, réseau, journaux et ressources.
- [x] Ajouter une validation locale immédiate des références réseau, IPv4, routes, câbles et nœuds du test de connectivité avant sauvegarde ou déploiement, avec erreurs marquées sur le schéma.
- [x] Ajouter le socle de l’étape 5 : parcours guidé étudiant, indice contextuel, états automatiques des critères, vérification de connectivité et visualisation du chemin logique du paquet.
- [x] Ajouter l’édition contrôlée des paramètres des nœuds personnalisés et du test de connectivité depuis l’interface.
- [x] Ajouter des modèles v2 prêts à l’emploi pour un réseau local simple et un scénario de routage statique client–routeur–serveur.
- [ ] Faire une revue de sécurité, activer HTTPS et définir le durcissement nécessaire avant une exposition publique.
- [x] Ajouter CoreDNS avec des enregistrements A validés dans les sous-réseaux du laboratoire, une configuration générée et montée en lecture seule.
- [ ] Ajouter DHCP/dnsmasq avec segments dédiés, configuration contrôlée et droits réseau minimaux.
- [x] Ajouter PostgreSQL, MySQL et MongoDB avec secrets hors topologie et volumes persistants.
- [ ] Ajouter WordPress, Jenkins, GitLab et Laravel avec dépendances, limites de ressources, volumes et images épinglées.
- [ ] Évaluer pfSense, MikroTik CHR et Windows Server/Active Directory sur un moteur VM/KVM avec validation de licences.


# Feuille de route de finalisation et présentation publique

## Priorité A — stabiliser l’expérience pédagogique Docker

- [ ] Remplacer les badges textuels de la palette par des pictogrammes SVG et représenter visuellement les switches et segments réseau.
- [ ] Permettre la sélection, la modification et la suppression individuelle des câbles, avec erreurs visibles sur câbles, ports et segments.
- [ ] Finaliser les exercices structurés avec objectifs, étapes, indices progressifs et niveaux d’aide.
- [ ] Déplacer l’évaluation des critères de réussite vers le backend et l’environnement réellement déployé.
- [ ] Ajouter des tests automatiques détaillés, des résultats structurés et une correction pédagogique.
- [ ] Ajouter des modèles complets pour IP, routage statique, VLAN, inter-VLAN, DNS, DHCP, firewall et services.
- [ ] Ajouter la visualisation animée du chemin réel d’un paquet lorsque les données d’exécution le permettent.

## Priorité B — industrialiser l’exécution distante

- [ ] Compléter la file de tâches, les leases, heartbeats, reprises et échecs définitifs.
- [ ] Gérer plusieurs workers distribués avec stockage partagé durable pour les données de laboratoires.
- [ ] Tester les pannes du control plane, du worker, du réseau et de la base.
- [ ] Tester la charge, la montée en charge, les déploiements concurrents, les expirations et les nettoyages.
- [ ] Définir et tester les objectifs RPO/RTO ainsi que la récupération après incident.

## Priorité C — élargir les services et environnements

- [ ] Finaliser DHCP/dnsmasq.
- [ ] Finaliser PostgreSQL, MySQL et MongoDB avec volumes, secrets, healthchecks et restauration.
- [ ] Intégrer Jenkins, GitLab, WordPress et Laravel avec dépendances et limites dédiées.
- [ ] Épingler les images par digest et contrôler leur provenance dans un registre maîtrisé.
- [ ] Intégrer libvirt/KVM puis étudier pfSense, MikroTik, Windows Server et Active Directory sous réserve des licences.

## Priorité D — supervision et assistance

- [ ] Historiser les métriques et afficher des graphiques temporels.
- [ ] Ajouter les alertes externes, notifications et quotas agrégés par utilisateur/laboratoire.
- [ ] Superviser les workers, jobs, bases et files d’exécution.
- [ ] Construire une assistance intelligente explicable basée sur la topologie, les routes, les logs et les états.
- [ ] Garantir que l’assistance ne modifie jamais silencieusement le réseau ou la topologie.

## Pré-requis avant preview publique contrôlée

- [ ] Définir clairement le périmètre expérimental et n’utiliser aucune donnée sensible réelle.
- [ ] Servir l’application derrière HTTPS avec cookies sécurisés, origines et hôtes autorisés.
- [ ] Stocker les secrets dans un gestionnaire dédié et activer la limitation de débit.
- [ ] Garder le socket Docker exclusivement sur un worker privé et utiliser mTLS control plane/worker.
- [ ] Appliquer des quotas stricts, des expirations et un nettoyage vérifiable des ressources.
- [ ] Tester les sauvegardes et la restauration complète.
- [ ] Limiter la preview aux images, scénarios et profils réellement maîtrisés.
- [ ] Préparer un plan d’arrêt d’urgence et une procédure d’incident.

## Pré-requis avant production publique

- [ ] Réaliser une revue de sécurité indépendante et des tests d’intrusion autorisés.
- [ ] Valider l’isolation entre laboratoires, utilisateurs et copies étudiantes.
- [ ] Mettre en place sauvegardes chiffrées, restauration régulière, rétention et purge contrôlées.
- [ ] Tester la haute disponibilité raisonnable, la reprise des workers et les déploiements concurrents.
- [ ] Ajouter les tableaux de bord, la rétention des métriques et les alertes opérationnelles.
- [ ] Fournir la documentation administrateur, enseignant, étudiant et exploitation.
- [ ] Publier les limites connues, les coûts de ressources et les profils effectivement supportés.
