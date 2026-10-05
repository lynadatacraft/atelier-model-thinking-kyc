# atelier-model-thinking-kyc

## Premier formulaire : lecture OCR locale et reponses sourcees

Ce prototype lit reellement le questionnaire scanne : OCR Tesseract via
PyMuPDF, detection des cellules de tableaux et des cases avec OpenCV,
identification des libelles, puis resolution a partir des sources d'Asterive.
Il ne contient plus de coordonnees fixes des champs ni de hash de gabarit impose.

### Installation et execution

Python 3.11 ou plus recent. Sous Windows :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_ocr.py
.\.venv\Scripts\python.exe fill_form01.py

```

Ne recreez pas un environnement existant avec une autre version de Python :
ses anciennes extensions binaires peuvent rester installees. Si NumPy signale
des fichiers `cp314` avec un interpreteur Python 3.13, reinstallez les
dependances avec l'interpreteur de cet environnement :

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

`setup_ocr.py` telecharge une seule fois les donnees publiques francaises et
anglaises de `tesseract-ocr/tessdata_fast` sur GitHub, dans `.ocr/`.
Il affiche leurs SHA-256. Aucun document d'entreprise n'est envoye.
Il n'est pas necessaire d'installer l'executable Tesseract :
le moteur OCR est integre a PyMuPDF. Une fois les dependances et langues
installees, l'execution est entierement hors ligne.

Sorties dans `output/form_01/` :

- `form_01_ocr.json` : mots reconnus, coordonnees en points PDF, cellules,
  cases detectees, langue, resolution et empreinte du document lu ;
- `form_01_answers.json` : 23 entrees avec page, libelle, valeur, etat,
  sources, justification, composants manquants, libelle effectivement
  reconnu et emplacement de la reponse ;
- `form_01_completed.pdf` : PDF rempli a partir de ces memes reponses.

Les chemins des preuves sont relatifs au dossier indique par `source_base`
dans le JSON. Pour les documents Markdown, les pointeurs portent sur leur
bloc JSON, pas sur le texte integral.

Options (le PDF alternatif doit contenir les questions du premier formulaire) :

```powershell
.\.venv\Scripts\python.exe fill_form01.py --pack ".\PARTICIPANT_PACK" --output ".\output\form_01"
.\.venv\Scripts\python.exe fill_form01.py --questionnaire ".\mon_formulaire.pdf" --tessdata ".\.ocr" --dpi 300
```

### Fonctionnement et perimetre

- [ocr_document.py](ocr_document.py) fournit la base reutilisable :
  rasterisation, suppression des grandes lignes pour faciliter l'OCR,
  extraction du texte, detection geometrique des cellules/cases et
  localisation des libelles. Les accents et la ponctuation sont normalises.
- [fill_form01.py](fill_form01.py) contient les regles metier du premier
  exercice : correspondance entre les questions reconnues et les sources.
  Cette correspondance semantique reste explicite ; aucun modele de langage
  ne decide automatiquement des questions inconnues.
- Les zones vides a droite des libelles sont deduites des cellules detectees.
  Les cases sont associees aux options Oui/Non/Envisagee reconnues par OCR.
  La date est placee autour des deux separateurs reperes sur la page.
- Un libelle absent ou ambigu, une cellule deja remplie, des cases non
  identifiables ou du texte impossible a inscrire provoquent une erreur.
  Aucun emplacement de gabarit fixe n'est utilise en secours.
  Le JSON OCR est conserve pour diagnostiquer une erreur de resolution.
- Le hash enregistre correspond au PDF effectivement lu, sans valeur
  predefinie. Il empeche de remplir un PDF modifie entre OCR et rendu.
- Aucun appel reseau pendant le traitement, modele distant, compte Supabase
  ou budget API. Dependances : PyMuPDF, NumPy et OpenCV headless.
- Les reponses viennent des documents corporate, activites et mandat.
  Les sources sont relues et leurs valeurs verifiees avant export.
- Le registre exhaustif des activites justifie les onze cases "Non".
  Une absence de registre ou une liste non vide bloque cet exemple au lieu
  de produire des reponses negatives injustifiees.
- La residence fiscale de la maison mere reste "Information manquante".
  Le marche de cotation est "Sans objet" car la societe n'est pas cotee.
- La date est celle de l'exercice, le 01/09/2026. Elle ne vaut pas signature :
  la confirmation et la signature restent une action humaine dans le JSON.
- Ce premier moteur OCR ne couvre pas seul les cinq exercices. Les scripts
  03 a 05 ci-dessous utilisent une autre approche, par gabarits calibres.
  Les scans doivent etre droits et suffisamment lisibles. Les formulaires
  arbitraires, manuscrits, sans tableaux ou deja remplis ne sont pas couverts.
- Relire visuellement le PDF avant remise : l'OCR ne garantit pas une
  interpretation parfaite. Le moteur ne fournit pas ici de score de confiance
  des mots ; aucun score fictif n'est ajoute.

Le temps d'execution peut etre mesure avec
`Measure-Command { .\.venv\Scripts\python.exe fill_form01.py }`.
Execution observee ici : environ 1,7 seconde pour deux pages a 300 DPI,
apres installation. Le cout API est de 0 ; le temps
depend de la machine. Les conditions de remise restent celles du
[pack participant](PARTICIPANT_PACK/READ_ME.md).

Les tests executent l'OCR reel, controlent les preuves et les marques dans
les cases, verifient les erreurs explicites et traitent une copie du PDF
decalee et reduite pour prouver que les positions ne sont pas codees en dur.

## Deuxieme formulaire : auto-certification fiscale de Belorive

```powershell
.\.venv\Scripts\python.exe fill_form02.py
```

Sorties : `output/form_02/form_02_completed.pdf`,
`output/form_02/form_02_answers.json` et `output/form_02/form_02_ocr.json`.
Les options `--pack`, `--output`, `--tessdata`, `--questionnaire` et `--dpi`
fonctionnent comme pour le premier script.

[fill_form02.py](fill_form02.py) utilise le manifeste pour retrouver les sources
du client. Il contient ses propres regles fiscales, pas les onze questions pays
du premier formulaire. Il reutilise la lecture des sources, les preuves et le
rendu PDF de [fill_form01.py](fill_form01.py) : conservez les deux fichiers.

Le moteur OCR commun detecte aussi les zones bleues, les en-tetes colores et
les colonnes/lignes de tableaux. Les labels courts sont recherches dans leur
section. Une bordure peu visible peut fusionner deux cellules : les limites
des colonnes voisines permettent de reconstituer la ligne. Si un repere
d'identite manque, les espacements d'une ligne complete du meme tableau sont
utilises ; le JSON comporte alors une `layout_note`. Sans repere suffisant,
le script s'arrete au lieu d'utiliser des positions fixes.

Le script renseigne l'identite, la residence fiscale francaise du client,
la categorie ENF passive, les trois beneficiaires effectifs et le representant.
Le NIF francais de Lea Montelac est conserve et son NIF americain reste
explicitement manquant. La signature, la certification et le cadre reserve
a la banque ne sont pas executes.

Limites : seules les regles du cas Belorive/ENF passive sont implementees ;
changer de statut necessite un autre traitement. Cela ne constitue pas une
interpretation automatique de questionnaires inconnus. L'OCR peut afficher
`Image too small to scale` ou `Line cannot be recognized` sur de petits
fragments du scan ; ces diagnostics ne sont pas masques. Les champs requis
doivent tout de meme etre localises et valides avant de produire les reponses.

Les tests du deuxieme formulaire verifient les preuves, le NIF partiel,
la case de statut, les quatre pages, une version decalee/reduite et le rejet
d'une entreprise ou d'un statut fiscal non pris en charge.

## Formulaires 03, 04 et 05 : gabarits calibres, sans OCR a l'execution

Les originaux sont des scans sans texte PDF natif. Pour ces questionnaires
connus, [questionnaire_common.py](questionnaire_common.py) charge la geometrie
persistante de [templates](templates), initialement extraite par OCR puis
corrigee pour les libelles ambigus et les petites cellules.
L'empreinte SHA-256 et les dimensions des pages doivent correspondre exactement.
Un autre PDF est refuse : aucune substitution silencieuse ni nouvel OCR.
Les formulaires 01 et 02 gardent leur fonctionnement OCR.

```powershell
.\.venv\Scripts\python.exe fill_form03.py
.\.venv\Scripts\python.exe fill_form04.py
.\.venv\Scripts\python.exe fill_form05.py
```

Les sorties sont `output/form_0N/form_0N_completed.pdf` et
`output/form_0N/form_0N_answers.json`. Les scripts utilisent les affectations
du pack : Cendrelis pour 03/05, Belorive pour 04. Les options utiles sont
`--pack`, `--output` et `--questionnaire` (copie identique uniquement).
`--dpi` et `--tessdata` sont conserves pour compatibilite mais ne sont pas
utilises par ces trois executions.

Les preuves sont verifiees avant rendu : pointeurs JSON ou lignes/citations
Markdown, calculs de pourcentages et composants manquants. Les longues
reponses portent un renvoi `See Rxxx` vers des pages de continuation dans
le meme PDF. Les champs d'action humaine et les signatures restent vierges.
Les donnees partielles restent presentes dans le JSON et la continuation.
Notamment : controle contractuel sans capital de Cendrelis, identifiant
manquant du representant Alex, validite/expiration non etablies de son
autorisation, et denominateur d'actifs groupe manquant de Belorive.

Les gabarits livres suffisent pour reproduire les sorties ; les fichiers
OCR intermediaires ne sont pas necessaires. [calibrate_templates.py](calibrate_templates.py)
est un outil de preparation pour reexporter les anciens fichiers
`output/form_0N/form_0N_ocr.json`, s'ils sont conserves. Il ne calibre pas
automatiquement un nouveau questionnaire : tout nouveau document necessite
une inspection des zones et une adaptation explicite des regles metier.
Le moteur est reutilisable, mais cette solution ne repond pas a l'objectif
plus large de generalisation automatique a des questionnaires inconnus.

Validation :

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Les tests des gabarits generent les trois PDF/JSON, interdisent l'appel OCR,
verifient les zones d'action humaine et le rejet d'un PDF different.
Execution observee pour ces deux tests : environ 1,7 seconde sur cette machine,
dependances deja installees. Cout API : 0. Plusieurs pages sensibles ont ete
inspectees visuellement ; relire tous les PDF et leurs continuations avant remise.
