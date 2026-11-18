# Images Netlab de laboratoire

Le scénario `../topology.json` utilise des images contrôlées afin de disposer de `ip`, `ping` et des outils réseau nécessaires. Construire les images avant le premier déploiement :

```bash
docker build -t netlab/ubuntu-lab:24.04 images/ubuntu-lab
docker build -t netlab/debian-lab:bookworm images/debian-lab
docker build -t netlab/debian-router:bookworm images/debian-router
```

Ces images sont adaptées au développement local. Avant un usage partagé, épingler les images de base par digest, scanner les images et ajouter un utilisateur non privilégié lorsque les opérations réseau le permettent.

## Utilisation avec Docker Compose

Construire ces trois images avant `docker compose up --build -d`. Le worker les utilise pour déployer `topology.json` et les modèles intégrés à l’interface.
