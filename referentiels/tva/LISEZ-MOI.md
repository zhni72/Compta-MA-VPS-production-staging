# Référentiels TVA (Simpl-TVA — relevé des déductions)

| Fichier | Rôle |
|---|---|
| `Annexe1_EDI_Simpl-TVA_Correspondance_Balise_RD_V4.0.pdf` | **Annexe officielle** « correspondance balise RD V4.0 » : chaque balise du fichier EDI, son libellé, son type — **et la codification des régimes de déclaration** |
| `annexe2_EDI_releveDeduction_Exemple_V2.0.xml` | **Exemple officiel** de fichier (fixture de test) |

## Ce que l'annexe V4.0 fixe (et que l'application respecte)

```
<regime>  1 = mensuel            2 = trimestriel
          3 = déclaration TVA de cessation temporaire d'activité
          4 = déclaration de cession ou cessation TVA
<periode> 1..12 (mensuel) | 1..4 (trimestriel) | 1 pour les régimes 3 et 4
```

- les **régimes 3 et 4** portent donc **`<periode>1</periode>`** : c'est le même fichier
  EDI que le relevé périodique, transmis avec la déclaration de cession/cessation
  (implémentation : `app/services/activity_events.py`, contrôle dans
  `app/services/edi_tva.validate_period()`) ;
- les autres balises (`identifiantFiscal`, `annee`, `releveDeductions`, `rd`, `ord`,
  `num`, `des`, `mht`, `tva`, `ttc`, `refF`, `if`, `nom`, `ice`, `tx`, `prorata`, `mp`,
  `id`, `dpai`, `dfac`) sont décrites dans le même tableau et implémentées par
  `app/services/edi_tva.py` ;
- `<prorata>` **n'est pas dans le XSD** mais figure dans l'annexe et l'exemple officiel
  (**pourcentage**) : il reste optionnel et paramétrable.

## Démarches fiscales correspondantes (CGI 2026 — édition fournie par le client)

| Situation | Texte | Délai / obligation |
|---|---|---|
| **Cession ou cessation** (TVA) | **art. 114** | déclaration **sous 30 jours** : liquidation de la taxe due + **régularisation des déductions** (renvoi aux art. 101 à 105) ; taxe exigible dans ce délai. **Exception** fusion / scission / apport / transformation si la nouvelle entité acquitte la taxe au fil des encaissements |
| **Cessation, cession, fusion, scission, transformation** | **art. 150-I** | déclaration **sous 45 jours** |
| **Cessation temporaire d'activité** | **art. 150 bis** | déclaration **dans le mois suivant la clôture** du dernier exercice, pour **2 exercices** renouvelable **1**, **motifs obligatoires** |
| **Régularisation des biens amortissables** | **art. 102 et 104-II-1°** | régularisation par fractions égales (durées « meubles » / « immeubles » **paramétrables** — ambiguïté A5) |

> ⚠️ Le projet citait auparavant « **CGI art. 106** » pour cette régularisation :
> l'article 106 traite en réalité des **opérations exclues du droit à déduction**.
> La correction des libellés déjà livrés est tracée comme action **D16** (CDC § 8.2, A23).
