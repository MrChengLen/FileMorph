# AGPLv3 für Behörden, Krankenhäuser und Kanzleien

FileMorph steht unter der **GNU Affero General Public License v3** (AGPLv3).
Diese Lizenz wird in Beschaffungsabteilungen gelegentlich als
"problematisch" wahrgenommen, weil das Wort *Affero* den Eindruck einer
Veröffentlichungspflicht erweckt. Dieses Dokument räumt das auf und
erklärt, was die AGPLv3 für eine deutsche Verwaltungs-, Kranken- oder
Kanzlei-Umgebung konkret bedeutet.

> **Hinweis:** Dieses Dokument ist eine Orientierungshilfe, keine
> Rechtsberatung. Für die verbindliche rechtliche Bewertung in Ihrem
> spezifischen Fall konsultieren Sie bitte Ihren Justiziar oder eine auf
> IT-Recht spezialisierte Kanzlei. Die anschließenden Aussagen
> beschreiben unsere Lesart der Lizenz, wie sie auch in der OSS-Community
> vorherrscht.

## Die Kurzfassung

| Sie tun … | Müssen Sie den Quellcode veröffentlichen? |
|---|---|
| FileMorph **intern** im Behörden-, Klinik- oder Kanzleinetzwerk betreiben | **Nein.** |
| FileMorph **modifizieren** und nur intern nutzen | **Nein.** |
| FileMorph **als SaaS für externe Dritte** anbieten (z. B. Bürgerportal) | **Ja**, gegenüber den Nutzern dieses Dienstes. |
| FileMorph als modifizierte Version **weitergeben** (Software-Distribution) | **Ja**, gegenüber dem Empfänger. |

Die meisten Behörden- und Healthcare-Deployments fallen in die ersten zwei
Zeilen — interne Nutzung. Hier entsteht **keine** AGPLv3-bedingte
Veröffentlichungspflicht.

## Worum es bei AGPLv3 wirklich geht

Die AGPLv3 ergänzt die GPLv3 um den sogenannten "Network-Use-Trigger"
(§13 AGPLv3). Sinn der Klausel: Die ursprüngliche GPL setzt die
Veröffentlichungspflicht erst beim *Verteilen* (engl. *conveying*) der
Software aus. SaaS-Anbieter haben das jahrelang umgangen — die Software
läuft nur auf ihren Servern, eine Distribution findet nicht statt.
Die AGPLv3 schließt diese Lücke: Wer die Software über ein Netzwerk
**externen Nutzern zugänglich macht**, muss den Nutzern dieses
Netzwerk-Dienstes den Quellcode (inkl. eigener Modifikationen) anbieten.

**Was die AGPLv3 *nicht* tut:**

- Sie erzwingt keine Veröffentlichung, wenn die Software nur intern in
  einer Organisation verwendet wird. Mitarbeitende einer Behörde sind
  keine "Dritten" im Sinne der Lizenz; sie sind dieselbe juristische
  Person wie der Betreiber.
- Sie verlangt keine Offenlegung Ihrer Behörden-Konfiguration,
  Ihrer Bürger-Daten oder anderer Inhalte, die Sie mit FileMorph
  verarbeiten.
- Sie verlangt keine Offenlegung anderer Software, die *neben* FileMorph
  läuft, solange diese Software nicht als integraler Bestandteil von
  FileMorph weitergegeben wird.

## Drei typische Behörden-Szenarien

### Szenario 1: FileMorph als interner Konvertierungsdienst

Eine Sozialverwaltung betreibt FileMorph auf einem internen Server.
Sachbearbeitende konvertieren Bürgerantrags-Anhänge nach PDF/A. Externe
Bürger interagieren mit dem Antragsportal, nicht mit FileMorph direkt.

→ **AGPLv3-konform ohne Veröffentlichungspflicht.** Die Software wird
intern genutzt; Sachbearbeitende sind keine externen Nutzer. Auch wenn
FileMorph an den Quelltext angepasst wird (interne Form-Vorlage,
LDAP-Anbindung), bleibt die Modifikation interne Sache der Behörde.

### Szenario 2: FileMorph eingebunden in ein öffentliches Bürgerportal

Eine Stadtverwaltung baut FileMorph als Konverter-Backend hinter ein
öffentlich zugängliches Bürgerportal. Bürger laden Dokumente hoch, das
Portal ruft FileMorph auf, gibt das konvertierte Ergebnis zurück.

→ **AGPLv3 §13 greift.** Die Behörde muss den Bürgern, die das Portal
nutzen, den Quellcode der eingesetzten FileMorph-Version anbieten —
inklusive eigener Modifikationen. Praktisch genügt ein Link auf ein
öffentliches Repository (typischerweise ein internes GitLab-Mirror) oder
auf das offizielle FileMorph-Repository, wenn die Version unverändert
übernommen wurde.

> Wenn diese Veröffentlichung organisatorisch unerwünscht ist, ist die
> **Compliance-Edition** mit kommerzieller Lizenz der saubere Weg —
> siehe `COMMERCIAL-LICENSE.md`. Die Compliance-Lizenz hebt die
> AGPLv3-Pflicht im Tausch gegen eine Lizenzgebühr auf.

### Szenario 3: FileMorph eingebettet in eine Eigenentwicklung

Eine Krankenhaus-IT entwickelt eine eigene Anwendung, die FileMorph als
Bibliothek (oder als Microservice) intern aufruft. Die Eigenentwicklung
selbst läuft nur im Krankenhausnetz.

→ **Keine Veröffentlichungspflicht.** Die Eigenentwicklung wird nicht
weitergegeben, FileMorph wird nicht extern angeboten — beide Trigger
entfallen.

## Wann eine kommerzielle Lizenz Sinn ergibt

Die Compliance-Edition (kommerzielle Lizenz) lohnt sich, wenn …

- Sie FileMorph als Backend für einen **öffentlich zugänglichen
  Online-Dienst** einsetzen und Modifikationen *nicht* veröffentlichen
  möchten (häufig bei Eigenentwicklungs-Erweiterungen, die einen
  Wettbewerbsvorteil bedeuten),
- Sie FileMorph **mit eigenen, geschlossen entwickelten Plug-ins**
  ausstatten, die unter eigener Lizenz bleiben sollen,
- Sie **vertraglich abgesicherte Support-SLAs** und einen festen
  Ansprechpartner für sicherheitskritische Updates benötigen,
- Sie eine **Air-Gap- oder KRITIS-Variante** mit garantierten
  Reaktionszeiten und Patch-Backports einsetzen wollen.

Für die rein interne Verwaltungs- oder Klinik-Nutzung ist dagegen die
**AGPLv3-Edition kostenfrei und vollumfänglich nutzbar**. Die meisten
unserer Behörden-Deployments laufen unter AGPLv3.

## Was im EVB-IT-Vertragswerk zu beachten ist

Mit der EVB-IT-Reform vom März 2026 ist Open-Source-Software erstmals
systematisch in den Vertragsbausteinen verankert: Open Source wird zum
Regelfall der öffentlichen IT-Beschaffung. Die AGPLv3 ist eine
OSI-zertifizierte und FSF-anerkannte Open-Source-Lizenz und damit von
diesen Regelungen ausdrücklich erfasst. Ergänzend kann beim
Vertragsabschluss ein **Software Bill of Materials (SBOM)** verlangt
werden — ein fehlendes oder unvollständiges SBOM kann künftig einen
Mangel darstellen. FileMorph liefert dieses Artefakt im
CycloneDX-Format mit jedem Release als `filemorph-{version}.cdx.json`
(siehe [`patch-policy.md`](./patch-policy.md)).

> **Wichtig für die Vertragswahl:** Die Reform betraf 8 der 11
> EVB-IT-Vertragstypen. **EVB-IT Cloud** und **EVB-IT Überlassung
> Typ B** wurden ausdrücklich **noch nicht** überarbeitet (eine
> Neufassung ist für später in 2026 angekündigt). Prüfen Sie deshalb
> für Ihren konkreten Vertragstyp, ob die neuen Open-Source- und
> SBOM-Regelungen dort bereits gelten.

Zur Einordnung: Die Reform folgt dem Grundsatz „Public Money, Public
Code" und macht Open Source zum Standard der Verwaltungsbeschaffung.
Sie stärkt damit ausdrücklich auch die **kostenfreie AGPLv3-Nutzung** —
eine kommerzielle Lizenz ist dafür nicht erforderlich (siehe die
Tabelle oben).

## Kontakt

Für lizenzrechtliche Rückfragen, eine schriftliche Bestätigung der
hier beschriebenen Lesart, oder ein Angebot für die Compliance-Edition
schreiben Sie an `licensing@filemorph.io`. Eine schriftliche
Bestätigung an Ihren Justiziar ist auf Anfrage und ohne
Zusatzkosten möglich.

## Quellen

- [GNU Affero General Public License v3](https://www.gnu.org/licenses/agpl-3.0.html) — der vollständige Lizenztext.
- [GNU AGPL FAQ](https://www.gnu.org/licenses/gpl-faq.html#UnreleasedMods) — die FSF erläutert die §13-Klausel und stellt explizit klar, dass interne Nutzung **keine** Veröffentlichungspflicht auslöst.
- [Open Source Initiative — AGPL-3.0 Approval](https://opensource.org/license/agpl-v3) — OSI-Zertifizierung.
- EVB-IT-Reform März 2026 (Open Source als Standard, SBOM-Anforderung; EVB-IT Cloud und Überlassung Typ B von dieser Runde ausgenommen): Berichterstattung u. a. von ZenDiS, der Open Source Business Alliance und der Kanzlei Luther.
