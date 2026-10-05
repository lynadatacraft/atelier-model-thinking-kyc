# Soumission achavaud - questionnaires KYC

## Livrables

| Exercice | Entreprise | PDF complete | Reponses sourcees |
|---|---|---|---|
| 01 | Asterive Services SAS | [PDF](outputs/form_01/form_01_completed.pdf) | [JSON](outputs/form_01/form_01_answers.json) |
| 02 | Belorive Patrimoine SAS | [PDF](outputs/form_02/form_02_completed.pdf) | [JSON](outputs/form_02/form_02_answers.json) |
| 03 | Cendrelis Instruments SAS | [PDF](outputs/form_03/form_03_completed.pdf) | [JSON](outputs/form_03/form_03_answers.json) |
| 04 | Belorive Patrimoine SAS | [PDF](outputs/form_04/form_04_completed.pdf) | [JSON](outputs/form_04/form_04_answers.json) |
| 05 | Cendrelis Instruments SAS | [PDF](outputs/form_05/form_05_completed.pdf) | [JSON](outputs/form_05/form_05_answers.json) |

Les fichiers OCR intermediaires des exercices 01/02 accompagnent leurs JSON.
Les sources d'entreprise et les PDF originaux restent dans le
[pack participant](../../PARTICIPANT_PACK/READ_ME.md), sans duplication.
`source_base` des JSON est relatif a `PARTICIPANT_PACK`; les chemins des
preuves sont relatifs au dossier d'entreprise ainsi designe.
`template_file` des JSON 03/04/05 est relatif au dossier [code](code).

## Reproduction sous Windows

Executer depuis la racine du depot, avec Python 3.11 ou plus recent :

```powershell
python -m venv .\SUBMISSIONS\achavaud\code\.venv
.\SUBMISSIONS\achavaud\code\.venv\Scripts\python.exe -m pip install -r .\SUBMISSIONS\achavaud\code\requirements.txt
.\SUBMISSIONS\achavaud\code\.venv\Scripts\python.exe .\SUBMISSIONS\achavaud\code\setup_ocr.py

foreach ($n in "01", "02", "03", "04", "05") {
    & .\SUBMISSIONS\achavaud\code\.venv\Scripts\python.exe ".\SUBMISSIONS\achavaud\code\fill_form$n.py" --pack ".\PARTICIPANT_PACK" --output ".\SUBMISSIONS\achavaud\verification\form_$n"
    if ($LASTEXITCODE -ne 0) { throw "Generation failed for form_$n" }
}
```

Les sorties de reproduction sont separees des livrables remis.
Le telechargement initial des langues OCR est public ; les documents
d'entreprise ne sont pas envoyes sur Internet. Aucun appel API de modele.
Pour les exercices 03/04/05 seuls, `setup_ocr.py` n'est pas necessaire.

### Tests

Les tests attendent le pack a cote des scripts. En preparer une copie locale
(ignoree par Git), puis executer :

```powershell
Copy-Item -LiteralPath .\PARTICIPANT_PACK -Destination .\SUBMISSIONS\achavaud\code -Recurse
.\SUBMISSIONS\achavaud\code\.venv\Scripts\python.exe -m unittest discover -s .\SUBMISSIONS\achavaud\code\tests
```

Validation avant soumission : 18 tests reussis sur Python 3.14.7,
environ 603 secondes pour la suite complete sur la machine de developpement.
Les deux tests des gabarits prennent environ 2 secondes. Cout API : 0.
Les dependances sont specifiees dans [requirements.txt](code/requirements.txt).

## Approche et limites

- 01/02 : OCR local PyMuPDF/Tesseract, detection de cellules/cases OpenCV,
  puis regles metier explicites et preuves verifiees.
- 03/04/05 : geometrie preparee par OCR et corrections de gabarit,
  persistante dans [templates](code/templates), protegee par empreinte SHA-256.
  Pas d'OCR a l'execution ; tout PDF different est refuse.
- Les longues reponses sont reliees par `See Rxxx` aux continuations
  ajoutees dans le meme PDF.
- Les composants connus des reponses partielles sont conserves ; les
  composants manquants sont identifies. Signatures et actions humaines ne
  sont pas executees. Les identifiants SIM restent ceux du scenario fictif.
- Les cinq questionnaires fournis sont pris en charge, mais pas
  l'interpretation autonome de questionnaires inconnus. Un nouveau
  questionnaire necessite un gabarit et des regles valides.
- Plusieurs pages sensibles ont ete inspectees visuellement, pas
  l'integralite des pages et continuations. Une relecture humaine reste
  necessaire avant utilisation.

Voir la [documentation technique](code/README.md) pour le fonctionnement
des scripts et les limites propres a chaque formulaire.
