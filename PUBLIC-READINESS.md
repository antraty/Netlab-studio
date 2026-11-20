# Netlab Studio — feuille de route et préparation publique

## Position actuelle

Netlab Studio est un prototype fonctionnel de plateforme de laboratoires réseau réels. Le cœur déjà disponible est :

- édition visuelle d’une topologie ;
- déploiement de vrais conteneurs Linux et de réseaux Docker ;
- interfaces IPv4, routes statiques et routeur Linux ;
- terminal WebSocket, journaux et métriques de ressources ;
- sauvegarde, restauration, clonage, import et export ;
- plusieurs laboratoires, rôles enseignant/étudiant et copies isolées ;
- affectations pédagogiques, critères, remises et corrections ;
- worker Docker séparé, PostgreSQL configurable et contrôles de sécurité de production ;
- parcours pédagogique initial avec objectifs, indices, critères et chemin logique du paquet.

Le projet n’est toutefois pas encore une plateforme publique prête à accueillir des utilisateurs inconnus. Il reste un prototype qui doit être durci, observé, sauvegardé et testé avant une exposition Internet.

## Travaux restant pour atteindre la vision

### Expérience Packet Tracer

- remplacer les badges textuels par de vrais pictogrammes SVG par type d’équipement ;
- représenter visuellement les switches et les segments réseau ;
- permettre de sélectionner, modifier et supprimer individuellement les câbles ;
- afficher les erreurs directement sur les câbles, ports et segments ;
- améliorer l’alignement, la grille et le placement des équipements ;
- gérer plus complètement les connexions multiples et les états de liaison ;
- faire du switch virtuel une appliance persistante et connectable plutôt qu’un simple segment Docker bridge.

### Pédagogie

- créer des exercices structurés avec objectifs, étapes, indices et niveaux d’aide ;
- déplacer l’évaluation des critères vers le backend et l’environnement réellement déployé ;
- fournir des tests automatiques détaillés et des résultats structurés ;
- proposer une correction automatique partielle et des explications compréhensibles ;
- ajouter le suivi de progression et les résultats par exercice ;
- créer des modèles complets : IP, routage statique, VLAN, inter-VLAN, DNS, DHCP, firewall et services ;
- animer le chemin réel d’un paquet lorsque les données d’exécution le permettent.

### Services et environnements

- finaliser DHCP/dnsmasq ;
- finaliser PostgreSQL, MySQL et MongoDB avec volumes, secrets, healthchecks et restauration ;
- intégrer Jenkins, GitLab, WordPress et Laravel avec dépendances et limites dédiées ;
- définir une politique d’images épinglées par digest et vérifiées dans un registre contrôlé ;
- intégrer ensuite libvirt/KVM, pfSense, MikroTik et Windows/Active Directory sous réserve des licences et de l’infrastructure.

### Exécution distante et cloud

- compléter la file de tâches et le cycle de vie des jobs ;
- fiabiliser les leases, heartbeats, reprises et échecs définitifs ;
- gérer plusieurs workers réellement distribués ;
- prévoir un stockage partagé durable pour les topologies et fichiers ;
- tester les pannes du control plane, du worker, du réseau et de la base ;
- effectuer des tests de charge et de montée en charge ;
- fournir nettoyage, expiration et récupération vérifiables après incident.

### Supervision et assistance

- historiser les métriques et construire des graphiques temporels ;
- ajouter alertes externes et notifications ;
- appliquer les quotas agrégés par utilisateur et laboratoire ;
- superviser workers, jobs, bases et files d’exécution ;
- construire l’assistance intelligente explicable à partir de la topologie, des routes, des logs et des états ;
- ne jamais modifier silencieusement une topologie ou une configuration.

## Conditions minimales avant présentation publique

### Sécurité d’accès

- utiliser HTTPS partout avec redirection HTTP vers HTTPS ;
- conserver `NETLAB_ENV=production`, des cookies `Secure` et des origines/hôtes explicitement autorisés ;
- stocker les secrets dans un gestionnaire de secrets, jamais dans Git ou `.env` public ;
- activer une limitation de débit au reverse proxy et une limitation persistante des tentatives de connexion ;
- définir une politique de sessions, de révocation, de rotation des secrets et de certificats ;
- fournir des rôles et permissions vérifiés par le backend, pas seulement masqués dans l’interface.

### Isolation d’exécution

- garder le socket Docker exclusivement sur le worker ;
- placer le worker sur un hôte privé et dédié, sans exposition Internet directe ;
- utiliser mTLS dans les deux directions entre control plane et worker ;
- filtrer les accès réseau entrants et sortants par laboratoire ;
- valider les privilèges, capabilities, volumes et images autorisés ;
- envisager un worker jetable ou une isolation renforcée de type gVisor/Kata pour les workloads non maîtrisés ;
- vérifier l’isolation entre utilisateurs, laboratoires et copies étudiantes par des tests dédiés.

### Données, sauvegardes et reprise

- utiliser PostgreSQL avec TLS en production ;
- automatiser les sauvegardes chiffrées ;
- tester régulièrement la restauration complète ;
- définir les objectifs RPO/RTO ;
- conserver les topologies, versions, remises, journaux et métadonnées dans un stockage durable ;
- documenter la récupération après perte de worker, de serveur ou de base ;
- mettre en place une rétention et une purge contrôlées.

### Exploitation

- servir le frontend compilé derrière la même origine HTTPS que l’API ;
- ne jamais utiliser Vite, `--reload` ou Swagger public en production ;
- ajouter un reverse proxy avec healthchecks, timeouts, limites et logs ;
- centraliser les logs et les corréler avec les jobs et les laboratoires ;
- ajouter des tableaux de bord et alertes opérationnelles ;
- documenter le déploiement, la mise à jour, le rollback et l’incident ;
- tester la charge, les expirations, les nettoyages et les déploiements concurrents.

### Qualité produit

- définir un périmètre public clair pour la première version ;
- limiter publiquement les profils à ceux réellement supportés et testés ;
- publier les prérequis, limites de ressources et limitations connues ;
- fournir un parcours de démonstration reproductible ;
- ajouter des tests frontend ciblés et des tests d’intégration de bout en bout ;
- tester les navigateurs et les écrans courants ;
- préparer une documentation enseignant, étudiant et administrateur ;
- faire une revue de sécurité indépendante et des tests d’intrusion autorisés avant ouverture.

## Définition pratique de « présentable publiquement »

Netlab Studio peut être présenté publiquement comme **prototype ou preview technique** dès lors que :

1. le périmètre est annoncé comme expérimental ;
2. aucune donnée sensible réelle n’est utilisée ;
3. l’accès est contrôlé ou limité à une démonstration ;
4. les images et topologies disponibles sont maîtrisées ;
5. les secrets sont correctement gérés ;
6. les sauvegardes et la restauration ont été testées ;
7. les logs, quotas et expirations sont surveillés ;
8. un plan d’arrêt d’urgence existe.

Pour une **ouverture publique à des utilisateurs inconnus**, il faut en plus valider l’isolation des workloads, l’audit de sécurité, la haute disponibilité raisonnable, les sauvegardes testées, la limitation de débit, les procédures d’incident et la capacité à supprimer proprement les ressources.

La recommandation est donc de distinguer deux jalons :

- **Preview publique contrôlée** : démonstration et petits groupes, périmètre Docker/Linux limité, workers isolés, quotas stricts et avertissement prototype ;
- **Version publique de production** : sécurité auditée, sauvegardes restaurables, exécution distribuée, observabilité historique, services sélectionnés et procédure d’incident éprouvée.
