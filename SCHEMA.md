# Tagging schema

The schema has a fixed **structure** (which tag holds what) and **vocabulary** derived
from your own library by `analyze_tags.py` (genre map, name spellings, bands that must not be split).

## Principles

1. **One value per person.** Multi-valued tags (`ARTISTS`, `COMPOSER`, `GENRE`...) hold a list,
   never a packed string like `"Lennon/McCartney"`. Players such as Navidrome, Jellyfin, Plex,
   foobar2000 and MusicBee then link each person separately.
2. **One canonical spelling per name.** `Beatles`, `the beatles`, `BEATLES` → `The Beatles`;
   `J.S. Bach`, `Bach, Johann Sebastian` → `Johann Sebastian Bach`.
3. **Display vs. sort.** Natural form for display, sort tag for ordering
   (`The Beatles` / `Beatles, The`; `Johann Sebastian Bach` / `Bach, Johann Sebastian`).
4. **Small, closed genre list + open styles.** `GENRE` uses ~19 top-level genres so browsing stays
   usable; the detail (`Hard Rock`, `Rumba Catalana`, `Baroque`) moves to `STYLE`, nothing is lost.
5. **Classical is first-class.** Composer, work, movement, conductor and ensemble have their own tags.

## Fields

| Field | ID3v2.4 (MP3) | FLAC / Ogg / Opus | MP4 / M4A | Multi | Example |
|---|---|---|---|---|---|
| ARTIST | TPE1 | ARTIST | ©ART | no | `Daft Punk feat. Pharrell Williams & Nile Rodgers` |
| ARTISTS | TXXX:ARTISTS | ARTISTS | ----:ARTISTS | **yes** | `Daft Punk` · `Pharrell Williams` · `Nile Rodgers` |
| ARTISTSORT | TSOP | ARTISTSORT | soar | no | `Beatles, The` |
| ALBUMARTIST | TPE2 | ALBUMARTIST | aART | no | `The Beatles` / `Various Artists` |
| ALBUMARTISTSORT | TSO2 | ALBUMARTISTSORT | soaa | no | `Beatles, The` |
| COMPILATION | TCMP | COMPILATION | cpil | no | `1` when album artist is Various Artists |
| COMPOSER | TCOM | COMPOSER | ©wrt | **yes** | `John Lennon` · `Paul McCartney` |
| COMPOSERSORT | TSOC | COMPOSERSORT | soco | **yes** | `Lennon, John` · `McCartney, Paul` |
| CONDUCTOR | TPE3 | CONDUCTOR | ----:CONDUCTOR | yes | `Herbert von Karajan` |
| ENSEMBLE | TXXX:ENSEMBLE | ENSEMBLE | ----:ENSEMBLE | yes | `Berliner Philharmoniker` |
| GENRE | TCON | GENRE | ©gen | **yes** (max 2) | `Rock` |
| STYLE | TXXX:STYLE | STYLE | ----:STYLE | yes | `Hard Rock`, `Baroque` |
| WORK | TXXX:WORK | WORK | ©wrk | no | `Cello Suite No. 1 in G major, BWV 1007` |
| MOVEMENTNAME | MVNM | MOVEMENTNAME | ©mvn | no | `Prélude` |
| MOVEMENT | MVIN | MOVEMENT | ©mvi | no | `1` |

| ALBUM | TALB | ALBUM | ©alb | no | `Beethoven - Symphonies Nos. 5 & 7 (BPhO / Herbert von Karajan)` |

(`----:` = `----:com.apple.iTunes:` freeform atoms.) Title, date, track numbers and
artwork are read but never modified. ALBUM is only rewritten for classical albums (see below).

## Rules

**Artists**
- `ARTIST` is rebuilt as `Main1 & Main2 feat. Guest1 & Guest2` from canonical names
  (`ft.`, `Feat`, `featuring`, `(feat. …)` all become ` feat. `).
- `ARTISTS` lists every individual act, including guests named in the title `Song (feat. X)`.
- Credits are split on ` & `, `, `, `;`, ` / `, ` + ` **except** names in `keep_together`.
  The analyzer fills that list from your library: a credit like `Simon & Garfunkel` whose parts
  never appear alone is one act; `Beyoncé & Jay-Z` (both appear alone) is split.

**Album artist**
- Same value on every track of an album (folder + album tag).
- Missing → the common artist; several different artists → `Various Artists` + `COMPILATION=1`;
  classical albums with a single composer → the composer (configurable: `composer|performer|keep`).

**Composers**
- Split into individual people, canonical full names, `COMPOSERSORT` as `Surname, Given names`
  (particles handled: `Beethoven, Ludwig van`, `Falla, Manuel de`).
- Built-in list of ~190 classical composers with spelling variants (`Tschaikowsky`, `Rachmaninov`,
  `Händel`, `J.S. Bach`…) and period. Ambiguous surnames (`Strauss`) are never guessed.
- Surname-only songwriter credits (`Lennon`) resolve to the full name found elsewhere in your library.
- Inference (proposed, never auto-approved if low confidence): `Bach: Cello Suite No. 1 - I. Prélude`
  → composer + work + movement; a composer sitting in ARTIST → copied to COMPOSER.

**Genres**
- Top level: Blues, Classical, Country, Electronic, Folk, Hip-Hop, Jazz, Latin, Metal, Pop,
  R&B & Soul, Reggae, Rock, Soundtrack, Spoken Word, World, Religious, Children's, Holiday
  (edit the `taxonomy` list freely).
- Every raw genre in your library is mapped in `[genre_map]` (`"Hard Rock" = ["Rock", "Hard Rock"]`);
  packed values like `Pop/Rock` are split first; ID3 numeric genres `(17)` are decoded.
- Classical tracks with a known composer get the period as STYLE (`Baroque`, `Romantic`, `Modern`…).
- If your player ignores STYLE, set `style_into_genre = true`.

**Classical album names** (`[album]` section; only albums that look classical)

```
{composer} - {works} ({performers})

Bach - Cello Suites Nos. 1–6 (Pablo Casals)                                  soloist
Beethoven - Symphonies Nos. 5 & 7 (BPhO / Herbert von Karajan)               orchestra + conductor
Beethoven - Violin Concerto, Op. 61 (Anne-Sophie Mutter; BPhO / Herbert von Karajan)   concerto: both
Falla - El amor brujo & El sombrero de tres picos (OBNC / Josep Pons)
Debussy, Satie, Albéniz - Clair de lune, Gymnopédie No. 1 & Asturias (Alexis Weissenberg)
```

- **Composer**: surname (`composer_name = "full"` for the full name); up to 3 composers, more → `Varios`.
- **Works**: taken from WORK, or from titles like `Symphony No. 5, Op. 67: I. Allegro` /
  `El amor brujo: Danza…`. Keys (`in C minor`, `en re menor`, `Es-Dur`) are dropped; the catalogue
  number is kept when there is a single work. Same type → grouped: `Symphonies Nos. 5 & 7`,
  `Cello Suites Nos. 1–6`. More than 3 → `A, B, etc.`
- **Performers**: each credit (ARTIST/ARTISTS, CONDUCTOR, ENSEMBLE) is classified:
  - *orchestra/ensemble* — name contains Orchestra, Orquesta, Orquestra, Philharmoni*, Symphon*,
    Sinfon*, Ensemble, Quartet, Choir/Coro/Cor, Kammer, Chamber, Academy, Consort, Kapelle… →
    shown as its **4-letter code** from `[orchestra_abbrev]` (the analyzer fills it with every
    orchestra in your library; ~60 well-known ones are built in: BPhO, WPhO, LSyO, RCGO, ASMF, OBNC…);
  - *conductor* — CONDUCTOR tag, `(cond.)`/`(dir.)` in the credit, or ~90 well-known conductors;
  - *soloist* — everyone else (`(piano)`, `(cello)` annotations are stripped).
  Only performers on ≥ 50 % of the album's tracks are named; composers are never listed as performers.
- Detected conductors and orchestras are also written to CONDUCTOR / ENSEMBLE.
- Two different albums that would get the same name are told apart by year (`[1962]`, `[1977]`),
  else by the old album name. CD1/CD2 sub-folders are treated as one album.
- Confidence *medium* (pre-approved) when composer and works were found in the tags/titles;
  *low* when works are just the track titles or the composer was guessed.
