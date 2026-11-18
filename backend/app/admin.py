from __future__ import annotations

import getpass
from urllib.parse import urlsplit

from .education import store


def create_teacher() -> int:
    print("Création locale d'un compte enseignant.")
    if store.postgres and store.database_url:
        database = urlsplit(store.database_url)
        name = database.path.lstrip("/") or "nom non précisé"
        host = database.hostname or "hôte configuré"
        print(f"Base PostgreSQL : {name} sur {host}")
    else:
        print(f"Base SQLite : {store.path}")
    email = input("Adresse e-mail du nouveau compte : ").strip()
    display_name = input("Nom affiché : ").strip()
    password = getpass.getpass("Mot de passe initial (12 caractères minimum) : ")
    confirmation = getpass.getpass("Confirmer le mot de passe : ")
    if password != confirmation:
        print("Erreur : les deux mots de passe ne correspondent pas.")
        return 2
    if input("Confirmer la création du compte (tapez CREER) : ") != "CREER":
        print("Création annulée.")
        return 1
    try:
        user = store.create_user(email, display_name, password, "teacher")
    except ValueError as exc:
        print(f"Erreur : {exc}")
        return 2
    print(f"Compte enseignant créé : {user['email']} ({user['id']})")
    print("Aucun compte ou laboratoire existant n'a été supprimé.")
    return 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Administration locale Netlab Studio.")
    parser.add_argument(
        "command",
        choices=["create-teacher"],
        help="créer un compte enseignant depuis la machine qui héberge la base",
    )
    arguments = parser.parse_args()
    if arguments.command == "create-teacher":
        raise SystemExit(create_teacher())


if __name__ == "__main__":
    main()
