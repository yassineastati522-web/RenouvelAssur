# RenouvelAssur

MVP de suivi des renouvellements de contrats pour une agence d’assurance. L’application est en français, responsive et fonctionne avec SQLite en local ou PostgreSQL en production.

## Fonctionnalités

- authentification sécurisée et rôles Administrateur / Agent ;
- tableau de bord : échéances, relances, renouvellements, primes et taux ;
- import de bordereaux Excel XLSX avec détection automatique de la feuille et de la ligne d’en-têtes ;
- reconnaissance des colonnes du bordereau assureur, validation, mise à jour idempotente et rapport d’erreurs ;
- liste des échéances à 7, 15, 30 ou 60 jours, recherche et filtres ;
- fiche contrat avec trois résultats d’appel : Client appelé, Boîte vocale et Non joignable ;
- checklist des clients à appeler avec recherche, filtre et enregistrement rapide du résultat ;
- statut de renouvellement géré séparément du résultat d’appel ;
- historique complet et non destructif des interactions ;
- fiches clients, téléphone modifiable et portefeuille associé ;
- contrats expirés sans renouvellement et résiliations ;
- suggestion « Injoignable » après trois tentatives infructueuses sur des jours distincts ;
- administration des utilisateurs et attributions via `/admin/`.

## Installation locale

Prérequis : Python 3.11 ou plus récent.

```powershell
cd outputs\assurance_renewal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Ouvrir `http://127.0.0.1:8000/`.

Comptes de démonstration :

- administrateur : `admin` / `Admin123!`
- agent : `agent` / `Agent123!`

Changez ces mots de passe avant toute utilisation réelle.

## Import Excel

Seuls les fichiers `.xlsx` sont acceptés. Le système inspecte les premières lignes des feuilles du classeur afin de trouver automatiquement le tableau principal.

Colonnes minimales : `Police`, `Client` ou `Assuré`, et `Date Échéance` ou `Date Fin`. Les en-têtes du bordereau fourni sont reconnus, notamment :

- `POLICE`, `Nature Evenement`, `CLIENT`, `NUMERO_CIN` ;
- `DATE_EFFET`, `DATE_ECHEANCE`, `DATE_EMISSION` ;
- `PRIME_TOTAL`, `PRIME_NET`, `NET_A_PAYE` ;
- `TELEPHONE`, `NUM_QUITTANCE`, `IMMATDEF`, `IMMAPRO`.

Les dates `JJ/MM/AAAA` et `AAAA-MM-JJ` sont acceptées. Les montants peuvent utiliser une virgule décimale. `IMMATDEF` est prioritaire sur `IMMAPRO`, avec repli automatique lorsque l’immatriculation définitive est vide. Les lignes de total du bordereau sont ignorées.

La combinaison `Police + Quittance` identifie un contrat ; un nouvel import met donc à jour la fiche existante au lieu de la dupliquer.

Un second fichier Excel ne contenant que `Téléphone` et un identifiant (`Police`, `CIN` ou `Client`) peut mettre à jour les contacts existants.

## Tests

```powershell
python manage.py test
python manage.py check --deploy
```

## PostgreSQL et production

Copier `.env.example` vers `.env`, charger les variables dans l’environnement et définir `POSTGRES_*`. En production, utiliser une clé `DJANGO_SECRET_KEY` longue, `DJANGO_DEBUG=0`, HTTPS, un serveur WSGI/ASGI et une sauvegarde régulière de la base. Le fichier `.env` n’est jamais versionné.

## Structure

- `renewals/models.py` : données et relations métier ;
- `renewals/services.py` : lecture, validation et import Excel ;
- `renewals/views.py` : permissions, filtres et tableaux de bord ;
- `templates/` et `static/css/` : interface ;
- `renewals/tests.py` : tests des flux critiques.
