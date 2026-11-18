from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ServicePort:
    container_port: int
    protocol: str = "tcp"
    host_publishable: bool = True


@dataclass(frozen=True)
class EnvironmentRequirement:
    name: str
    required: bool
    secret: bool
    purpose: str


@dataclass(frozen=True)
class ServiceProfile:
    id: str
    label: str
    category: str
    status: str
    image: str | None
    command: tuple[str, ...]
    ports: tuple[ServicePort, ...]
    primary_port: int | None
    resources: dict[str, int | float]
    environment: tuple[EnvironmentRequirement, ...]
    constraints: tuple[str, ...]

    @property
    def deployable(self) -> bool:
        return self.status == "ready"

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["command"] = list(self.command)
        data["ports"] = [asdict(port) for port in self.ports]
        data["environment"] = [asdict(item) for item in self.environment]
        data["constraints"] = list(self.constraints)
        data["deployable"] = self.deployable
        return data


_READY_CONSTRAINTS = (
    "Image officielle sélectionnée ; le tag reste mutable, épingler un digest avant un usage partagé.",
    "Conteneur limité en mémoire, CPU et nombre de processus par le prototype.",
    "Les ports sont internes au réseau Docker par défaut ; un port hôte facultatif est lié uniquement à 127.0.0.1.",
    "Les liens de l’éditeur ne créent pas encore des réseaux Docker isolés.",
)

PROFILES: tuple[ServiceProfile, ...] = (
    ServiceProfile(
        id="nginx", label="Nginx — serveur web", category="web", status="ready",
        image="nginx:stable-alpine", command=("nginx", "-g", "daemon off;"),
        ports=(ServicePort(80), ServicePort(443)), primary_port=80,
        resources={"memory_mb": 512, "cpu_cores": 0.5, "pids": 128}, environment=(),
        constraints=_READY_CONSTRAINTS + ("La configuration et les fichiers du site ne sont pas encore montés depuis un volume.",),
    ),
    ServiceProfile(
        id="apache", label="Apache HTTP Server", category="web", status="ready",
        image="httpd:2.4-alpine", command=("httpd-foreground",),
        ports=(ServicePort(80),), primary_port=80,
        resources={"memory_mb": 512, "cpu_cores": 0.5, "pids": 128}, environment=(),
        constraints=_READY_CONSTRAINTS + ("La configuration et les fichiers du site ne sont pas encore montés depuis un volume.",),
    ),
    ServiceProfile(
        id="coredns", label="CoreDNS — DNS autoritatif de laboratoire", category="dns", status="ready",
        image="coredns/coredns:1.12.0", command=("-conf", "/etc/coredns/Corefile"),
        ports=(ServicePort(53, "udp", False), ServicePort(53, "tcp", False)), primary_port=None,
        resources={"memory_mb": 256, "cpu_cores": 0.25, "pids": 64}, environment=(),
        constraints=_READY_CONSTRAINTS + (
            "Les entrées A sont générées depuis la topologie et limitées aux adresses IPv4 des sous-réseaux du laboratoire.",
            "Le DNS écoute uniquement dans les segments du laboratoire ; aucune publication de port hôte n’est disponible.",
        ),
    ),
    ServiceProfile(
        id="dnsmasq", label="dnsmasq — DNS/DHCP", category="network", status="planned",
        image="dockurr/dnsmasq:latest", command=(), ports=(ServicePort(53, "udp", False), ServicePort(67, "udp", False)), primary_port=None,
        resources={"recommended_memory_mb": 256, "recommended_cpu_cores": 0.25}, environment=(),
        constraints=("DHCP exige un réseau dédié, des droits réseau minimaux et un contrôle strict des broadcasts.", "NET_ADMIN, isolation de segments et configuration DHCP ne sont pas implémentés ; aucun privilège n’est accordé par défaut."),
    ),
    ServiceProfile(
        id="postgresql", label="PostgreSQL", category="database", status="planned",
        image="postgres:17-alpine", command=(), ports=(ServicePort(5432, host_publishable=False),), primary_port=None,
        resources={"recommended_memory_mb": 1024, "recommended_cpu_cores": 1},
        environment=(EnvironmentRequirement("POSTGRES_USER", True, False, "Nom du compte initial."), EnvironmentRequirement("POSTGRES_PASSWORD", True, True, "Mot de passe initial obligatoire."), EnvironmentRequirement("POSTGRES_DB", False, False, "Base initiale.")),
        constraints=("Aucun gestionnaire de secrets ni volume de données persistant n’est encore disponible.", "Ne pas enregistrer de mot de passe dans une topologie versionnée.",),
    ),
    ServiceProfile(
        id="mysql", label="MySQL", category="database", status="planned",
        image="mysql:8.4", command=(), ports=(ServicePort(3306, host_publishable=False),), primary_port=None,
        resources={"recommended_memory_mb": 1024, "recommended_cpu_cores": 1},
        environment=(EnvironmentRequirement("MYSQL_ROOT_PASSWORD", True, True, "Mot de passe root initial obligatoire."), EnvironmentRequirement("MYSQL_DATABASE", False, False, "Base initiale."), EnvironmentRequirement("MYSQL_USER", False, False, "Compte applicatif."), EnvironmentRequirement("MYSQL_PASSWORD", False, True, "Mot de passe applicatif.")),
        constraints=("Aucun gestionnaire de secrets ni volume de données persistant n’est encore disponible.", "Ne pas enregistrer de mot de passe dans une topologie versionnée."),
    ),
    ServiceProfile(
        id="mongodb", label="MongoDB", category="database", status="planned",
        image="mongo:8", command=(), ports=(ServicePort(27017, host_publishable=False),), primary_port=None,
        resources={"recommended_memory_mb": 2048, "recommended_cpu_cores": 1},
        environment=(EnvironmentRequirement("MONGO_INITDB_ROOT_USERNAME", True, False, "Compte administrateur initial."), EnvironmentRequirement("MONGO_INITDB_ROOT_PASSWORD", True, True, "Mot de passe initial obligatoire.")),
        constraints=("Aucun gestionnaire de secrets ni volume de données persistant n’est encore disponible.", "Ne pas enregistrer de mot de passe dans une topologie versionnée."),
    ),
    ServiceProfile(
        id="wordpress", label="WordPress", category="application", status="planned",
        image="wordpress:php8.3-apache", command=(), ports=(ServicePort(80),), primary_port=None,
        resources={"recommended_memory_mb": 1024, "recommended_cpu_cores": 1},
        environment=(EnvironmentRequirement("WORDPRESS_DB_HOST", True, False, "Adresse du service de base."), EnvironmentRequirement("WORDPRESS_DB_USER", True, False, "Compte de base."), EnvironmentRequirement("WORDPRESS_DB_PASSWORD", True, True, "Mot de passe de base."), EnvironmentRequirement("WORDPRESS_DB_NAME", True, False, "Nom de la base.")),
        constraints=("Dépend d’un service de base persistant et de secrets gérés hors topologie.", "Publication hôte et stockage WordPress non implémentés."),
    ),
    ServiceProfile(
        id="jenkins", label="Jenkins", category="devops", status="planned",
        image="jenkins/jenkins:lts-jdk21", command=(), ports=(ServicePort(8080), ServicePort(50000, host_publishable=False)), primary_port=None,
        resources={"recommended_memory_mb": 4096, "recommended_cpu_cores": 2}, environment=(),
        constraints=("Service gourmand ; volume Jenkins Home, sauvegarde, gestion des plugins et limites dédiées requis.", "Ne pas monter le socket Docker de l’hôte dans ce prototype."),
    ),
    ServiceProfile(
        id="gitlab", label="GitLab CE", category="devops", status="planned",
        image="gitlab/gitlab-ce:latest", command=(), ports=(ServicePort(80), ServicePort(443), ServicePort(22, host_publishable=False)), primary_port=None,
        resources={"recommended_memory_mb": 8192, "recommended_cpu_cores": 4}, environment=(EnvironmentRequirement("GITLAB_OMNIBUS_CONFIG", False, True, "Configuration initiale potentiellement sensible."),),
        constraints=("Service très gourmand ; stockage durable, stratégie de sauvegarde et ports SSH dédiés requis.", "Image taguée latest à remplacer par un digest validé avant intégration."),
    ),
    ServiceProfile(
        id="laravel", label="Laravel", category="application", status="planned",
        image="laravelsail/php84-composer", command=(), ports=(ServicePort(80),), primary_port=None,
        resources={"recommended_memory_mb": 1024, "recommended_cpu_cores": 1},
        environment=(EnvironmentRequirement("APP_KEY", True, True, "Clé applicative à générer et conserver secrètement."), EnvironmentRequirement("DB_PASSWORD", False, True, "Mot de passe de base.")),
        constraints=("Dépendances PHP, source applicative, base, secrets et volumes non orchestrés par le prototype."),
    ),
    ServiceProfile(
        id="pfsense", label="pfSense CE", category="appliance", status="research",
        image=None, command=(), ports=(), primary_port=None,
        resources={"recommended_memory_mb": 2048, "recommended_cpu_cores": 2}, environment=(),
        constraints=("Nécessite une intégration VM/KVM, des interfaces réseau dédiées et la vérification des conditions d’utilisation de l’image." ,),
    ),
    ServiceProfile(
        id="mikrotik-chr", label="MikroTik CHR", category="appliance", status="research",
        image=None, command=(), ports=(), primary_port=None,
        resources={"recommended_memory_mb": 1024, "recommended_cpu_cores": 1}, environment=(),
        constraints=("Nécessite une intégration VM/KVM et le respect du modèle de licence CHR." ,),
    ),
    ServiceProfile(
        id="windows-server", label="Windows Server / Active Directory", category="appliance", status="research",
        image=None, command=(), ports=(), primary_port=None,
        resources={"recommended_memory_mb": 4096, "recommended_cpu_cores": 2}, environment=(),
        constraints=("Nécessite des machines virtuelles, KVM, licences Windows et un provisionnement spécialisé." ,),
    ),
)

_BY_ID = {profile.id: profile for profile in PROFILES}


def get_service(service_id: str) -> ServiceProfile | None:
    return _BY_ID.get(service_id)


def list_services() -> list[dict[str, Any]]:
    return [profile.public_dict() for profile in PROFILES]


def validate_catalog_node(service_id: str | None, image: str, command: list[str], published_port: int | None) -> None:
    if service_id is None:
        if published_port is not None:
            raise ValueError("host port publishing is only available for a deployable catalog service")
        return
    profile = get_service(service_id)
    if not profile:
        raise ValueError(f"unknown service profile: {service_id}")
    if not profile.deployable:
        raise ValueError(f"service profile is not deployable yet: {service_id}")
    if image != profile.image or tuple(command) != profile.command:
        raise ValueError(f"image and command for {service_id} must match the catalog profile")
    if published_port is not None and profile.primary_port is None:
        raise ValueError(f"service profile does not support host port publishing: {service_id}")
