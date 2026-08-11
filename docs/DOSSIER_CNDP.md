# Trame de préparation du dossier CNDP

Cette trame rassemble les informations à faire confirmer par la CNDP ou un juriste marocain. Elle ne détermine pas à elle seule le régime juridique applicable.

## 1. Responsable et périmètre du traitement

- Raison sociale, adresse et représentant habilité de l’agence : **à renseigner**.
- Contact pour l’exercice des droits : **à renseigner**.
- Nom du traitement : suivi des échéances, renouvellements, résiliations, provisoires et relances téléphoniques.
- Personnes concernées : assurés, contacts des contrats et utilisateurs de l’agence.
- Finalités exactes : gérer le portefeuille, organiser les appels, suivre les résultats, importer les données de l’assureur et conserver une traçabilité de sécurité.
- Base et formalité CNDP existantes de l’agence : **à joindre et à faire vérifier**.

La CNDP indique qu’un traitement doit avoir une finalité précise, rester proportionné et être notifié avant sa mise en œuvre. L’utilisation de la CIN figure parmi les situations pouvant nécessiter une autorisation préalable. Vérifier si le traitement relève d’une déclaration normale, d’une autorisation, d’une décision existante ou d’une modification d’un dossier déjà approuvé.

Références officielles :

- https://www.cndp.ma/conditions/
- https://www.cndp.ma/procedures-de-notification-process/

## 2. Données, sources et destinataires

| Catégorie | Source | Utilité | Destinataires autorisés | Conservation proposée |
|---|---|---|---|---|
| Identité et contact | Fichiers assureur / agence | Identifier et appeler l’assuré | Agents autorisés | À valider |
| Police, véhicule, dates et primes | Fichiers assureur | Suivre le contrat et son renouvellement | Agents autorisés | À valider |
| Résultat d’appel et tentatives | Utilisateur de l’agence | Organiser les relances | Agents autorisés | À valider |
| Historique d’import | Application | Traçabilité des sources | Administrateurs | À valider |
| Journal d’audit | Application | Sécurité et responsabilité | Administrateurs habilités | 730 jours proposés |
| Comptes et rôles | Agence | Contrôle d’accès | Administrateurs | Durée du compte + délai à valider |

Documenter les colonnes exactes importées. Écarter toute colonne non nécessaire. Les commentaires libres doivent rester limités et ne pas contenir d’informations sensibles inutiles.

## 3. Hébergement et transferts à l’étranger

Le service Render est configuré dans la région `frankfurt` du fichier `render.yaml`, donc l’instance applicative demandée est en Allemagne. Cela ne prouve pas que tous les journaux, sauvegardes, services de support ou sous-traitants ultérieurs restent dans ce même pays.

Pour Neon, relever dans la console du projet la région et le fournisseur exacts de la base utilisée. Ne pas écrire simplement « Europe ». Compléter le tableau suivant à partir des contrats et listes de sous-traitants à jour :

| Prestataire / fonction | Entité contractante | Pays de l’entité | Localisation des données principales | Journaux / sauvegardes / support | Sous-traitants | Preuve jointe |
|---|---|---|---|---|---|---|
| Render / application | À vérifier | À vérifier | Allemagne, région demandée `frankfurt` | À vérifier | À vérifier | Contrat + liste actuelle |
| Neon / PostgreSQL | À vérifier | À vérifier | À relever dans Neon | À vérifier | À vérifier | Contrat + écran de région |
| Sentry, si activé / erreurs | À vérifier | À vérifier | À choisir et vérifier | Corps, cookies et identité supprimés par l’application; infrastructure à vérifier | À vérifier | Contrat + configuration |
| Sauvegarde externe éventuelle | À renseigner | À renseigner | À renseigner | À renseigner | À renseigner | Procédure + contrat |

La CNDP précise qu’un transfert à l’étranger utilise le formulaire F118 et que le traitement sous-jacent doit d’abord avoir été déclaré ou autorisé. Le dossier peut notamment exiger les clauses contractuelles et les références du traitement.

Référence officielle : https://www.cndp.ma/transfert-de-donnees-a-letranger/

## 4. Contrats et information des personnes

Réunir :

- contrat ou avenant avec chaque sous-traitant : instructions, confidentialité, sécurité, incidents, sous-traitants ultérieurs, audit, restitution et suppression ;
- liste des personnes et rôles autorisés dans l’agence ;
- mention d’information remise aux assurés : responsable, finalités, données obligatoires, destinataires au Maroc et à l’étranger, droits, contact, référence CNDP et transfert ;
- procédure d’accès, rectification et opposition avec responsable et délai de réponse ;
- preuve de l’information ou du consentement lorsque le conseil le juge nécessaire.

La CNDP publie des mentions types, dont un exemple de clause de sécurité pour la sous-traitance : https://www.cndp.ma/mentions-types/

## 5. Mesures de sécurité à joindre

- HTTPS, HSTS, CSP, cookies de session sécurisés et protection CSRF ;
- mots de passe contrôlés, blocage après échecs et déconnexion à minuit ;
- MFA TOTP obligatoire pour les administrateurs et codes de secours à usage unique ;
- rôles Administrateur / Agent, restrictions sur l’administration et révocation des sessions ;
- journal d’audit minimisé, non modifiable depuis l’administration et export limité ;
- contrôle de type, taille et contenu des fichiers importés ;
- PostgreSQL chiffré en transit, secrets hors du dépôt et procédure de rotation ;
- sauvegarde/restauration testée et plan de réponse aux incidents ;
- surveillance Sentry optionnelle avec minimisation explicite des événements.

Joindre les résultats datés des tests, du contrôle Django, de l’audit des dépendances et d’un exercice de restauration.

## 6. Décisions à faire valider avant production

1. Quelle formalité correspond exactement à l’activité d’assurance et à l’utilisation éventuelle de la CIN ?
2. L’autorisation existante de l’agence couvre-t-elle ce logiciel, les relances et l’hébergement cloud ?
3. Quels pays, entités et garanties doivent être indiqués dans le F118 pour Render, Neon, Sentry et les sauvegardes ?
4. Quelles durées appliquer aux contrats, résiliations, provisoires, appels, imports et audits ?
5. Quelle mention d’information doit être remise aux assurés et sur quel support ?
6. En cas de commercialisation à plusieurs agences, qui sera responsable de traitement, sous-traitant ou sous-traitant ultérieur, et quelle formalité chaque agence devra-t-elle accomplir ?

Conserver la réponse écrite de la CNDP ou du conseil avec la version du dossier, la date et le signataire.
