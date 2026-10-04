# User-defined contests (UDC)

[Step-by-step UDC + SEC + HLP setup with screenshots](udc-setup.md).

File → **Import User Contest…** imports original N1MM `.udc` files. Review the
mode, exchange, scoring, author, revision, dependencies and geography, then click
Import. The contest appears in **New Contest** with a `[UDC]` suffix. Enter your
own exchange, start date and categories there; configure the station before
creating the journal. No Python plugin, launcher or subsequent application build
is needed to add another supported definition.

An autonomous definition needs one file. Section lists (`.sec`) and bonus lists
(`.txt`) remain separate. The importer uses matching files beside the definition,
or files explicitly selected with **Add dependency files**. It does not download
anything. Missing dependencies or active unsupported rules prevent registration.
UTF-8 and UTF-16/32 with BOM are detected; choose a legacy encoding explicitly.

Select a contest-specific CTY.DAT when its instructions require one. The dialog
suggests a single adjacent `*cty.dat` and shows it in the preview. Geography is local to this journal and never replaces the
application's country database.

Rules, dependency bytes, geography, engine version and station identity are saved
in SQLite when a journal is created. Re-importing a revised definition affects
new journals. Existing journals still open after catalog/source files disappear.
The station identity is fixed at journal creation; contest categories and sent
exchange remain editable through the normal contest settings dialog.

**Export User Contest Definition…** exports the original UDC and separate
resources from the current journal's snapshot. Existing different files are not
overwritten. Cabrillo 2/3 and ADIF use the same evaluated contacts as the score
shown in the window. Duplicates remain in the log and exports, with zero points.

## Compatibility contract

This is a checked subset of N1MM UDC, not a claim of complete N1MM emulation.
The executable contract is `not1mm/udc/model.py` plus `engine.validate_rules` and
resource validation. Unknown active options/selectors fail with the parameter
name and value. Empty editor-template options and disabled deferred options are
accepted. N1MM macros, CallHistory multipliers, LASTEXCH, network Multi-Multi and
SWL are not implemented. No SQL, Python, expressions or shell commands from UDC
are executed. `MultSqlString` and `DupeSqlString` are enumerated selectors.

| Parameters | Supported behavior / boundary |
|---|---|
| Name, DisplayName, CabrilloName | Separate stable catalog identity, display and export names; builtin identities cannot be shadowed |
| Mode | CW, SSB, BOTH, RTTY; normalized USB/LSB/CW variants and PSK; BOTH accepts FT8/FT4/FM/AM. RTTY does not implicitly authorize FT modes |
| EntryWindowInfo, FrameText, LogInfo | Existing DXLOG fields; dynamic extra inputs, Tab/Enter, column selection; unknown log columns fail |
| QsoErrorString | Any / Numeric with optional nonempty suffix, field-specific checks, grid4/6, external section list; received numeric serials |
| DupeType, DupeSqlString | Contest/band/band-mode/no checking, extra section/exchange/mode/grid identity |
| DupeQSOMinutesAgo | Scalar minutes, or N1MM five-part minutes/CompareToSecond/IgnoreBand/InfoStatus/ThisMode. Scalar preserves the previous credited-QSO anchor and DupeType scope; five-part rules use the last recorded matching QSO, independent band/mode flags and the fixed session. DupeType=4 works. New contact allowed at the exact interval boundary |
| MultipleSessions | UTC HHMM/HHMM tours; date participates in identity; no implied event end |
| ResetMultsEverySession, ResetSNEverySession | Independent resets, each off by default |
| QsoNumbersByBand | Global, per-band, or per-band for unlimited-transmitter category |
| PointsPerContact | Integer; named country/continent/mode/band conditions, own exchange/zone/grid, text/numeric conditions; radial distance tables; VHF distance times factor |
| PointsMultByBand/Mode/Continent/Country/Category | Numeric factors, with first matching selector in each family. DIGI matches RTTY/PSK/DIGI/FT8/FT4 in engine 3; FT8/FT4 can have their own conditions |
| PointsMultAtTimeGMT / PointMultAtTimeGMT | UTC time window, including midnight crossing |
| BonusPoints | Conditional replacement, additive or multiplicative bonuses; numeric exchange/misc/comment sources |
| BonusPoints2 | Separate callsign lists or grid/point tables; validated filenames, no automatic download |
| NumMults, MultSqlString/2/3 | Up to three groups: DXCC, sections, WPX, grid4/grid6/field, callsign, first QSO, misc/exchange, CQ/IARU zone, two letters, last letter, continent-restricted DXCC |
| IsMultPer, IsMult1Per/2Per/3Per | No multiplier, per-band, per-mode, per-band-mode, whole contest |
| CountMultOnlyFor*, DoNotCountMultOnlyFor*, CountMultOnlyForSec* | Country/continent and section filters |
| DoNotCountMeAsMult* | Own country, section, grid/field or WPX; incompatible selectors rejected |
| MultMult/2/3 | Keep a group visible while excluding it from score |
| IsWorkable | Any, geographic inclusion/exclusion, explicit country list; non-scoring QSO retained |
| DigitalModeSqlString | RTTY and PSK share duplicate/multiplier mode identity |
| ShowWarcBands | WARC contacts rejected unless enabled |
| CQZoneMultContest | Requires an explicit CQZONE selector; never invents an implicit group |
| CabrilloVersion, CabrilloFormat, CabrilloString | Versions 2/3; standard format 1 and explicit format 99; supported field/width tokens only |
| DefaultContestExchange, SpecialInstructions, author/revision | Import preview and creation hints; do not hard-code the operator into a definition |
| GenericPrintString/Header, multiplier labels, Period, WebAddress, OverlayCategory | Descriptive/N1MM presentation metadata; N1MM printer/summary windows are not emulated |
| StartOfContest, EndOfContest, MinimumOffTime | Typed recurring UTC calendar hints (Saturday=1), full-clock-minute OFF report with threshold for internal gaps; leading/trailing full minutes count as OFF. Identical endpoints require an explicit interval in File → UDC operating / OFF times. These parameters do not impose QSO scoring limits |
| MultiplierBands | 1 HF contest bands, 2 all HF, 3 HF contest + 6m/2m, 4 VHF/UHF; multiplier eligibility follows the selected set, independently of per-band/mode scope |
| SingleOpCountableBandChange, MultiOpCountableBandChange, SO/MOBandChangeCountMax | Counters per radio, activated by logged QSOs, with yellow at max-1/red at max; warnings beyond max. Initial QSO is not a change, duplicates still count as operating activity |
| CountBandOrModeChange, CountBandChangesPerContest/Period | Optionally count mode changes; scope whole journal, fixed session, or UTC clock hour. Simultaneous contest+period scopes rejected |
| SO/MOBandChangeTimerDuration | Hold timer starts on the first QSO and restarts on a band change, independently of mode-only counters. Early band changes generate warnings. Contacts and points are retained |
| BandChangesPerPeriod | Legacy limit fallback when no modern band-change option is active; modern options take precedence over obsolete template defaults |
| WSJT-X logged ADIF | Validated UDP type 12 packets, FT4 MODE=MFSK/SUBMODE=FT4, original UTC time/frequency/signed reports, same converter as ADIF import. Repeated delivery is idempotent across journal reopen; genuine subsequent QSOs remain, including dupes |
| Section files | Single spelling or two-column spelling → section records, tab/comma/whitespace separated; ambiguous aliases rejected. Received Exchange1 stays unchanged; normalized Sect is used for multipliers |
| Local-time scoring, PowerMult, UsesWAECountries, sent-time/previous-contact exchange | Active values rejected; require additional documented implementation and tests |

Specific exchange tests precede generic geographic fallbacks. Explicit band
conditions precede mode conditions; equally specific rules retain declaration
order. A supported file is not a substitute for reviewing the published event
rules: an omission in the original
UDC cannot be inferred from its prose description.

ADIF exports standard exchange fields and `APP_NOT1MM_*` fields for a lossless
round trip, including empty exchange values. Imports use explicit tags first,
then unambiguous SRX_STRING components. Ambiguous compound strings fail rather
than silently losing part of an exchange.

## Storage and architectural decisions

- The registry reads existing builtin labels and keeps their historical module
  IDs. `BuiltinContest` delegates the existing module API. User IDs have a separate
  `udc:` namespace based on Name and author callsign, independent of DisplayName
  and revision. One `UdcContest` instance owns each loaded journal's state.
- The parser produces immutable typed definitions and field descriptors. The
  evaluator accepts plain DXLOG dictionaries and has no Qt dependency. UDC
  definitions are data, with enumerated selectors rather than executable rules.
- The user catalog installs content-addressed bundles and atomically replaces a
  small current-revision reference. Files inside SQLite are deduplicated by SHA-256.
  Checksums and engine version are verified when loading snapshots. There is no
  fallback to changed external files if a journal snapshot is corrupt or missing.
- Schema initialization takes a SQLite backup (including committed WAL data),
  then uses one transaction. It adds UdcResource/UdcJournal and extends DXLOG's
  legacy primary key `(TS, Call)` to `(TS, Call, ContestNR, ID)`. This structural
  change is necessary for independent journals and same-second duplicate entries.
  Existing QSO values are copied unchanged and checked before the old table is
  replaced; indexes/triggers are retained. No old QSO is rescored or reinterpreted.
  An unfamiliar key/schema is refused. Normal legacy-only startup does not migrate.
- Insert, edit, delete and batch ADIF import evaluate the complete affected
  journal before writing. Invalid operations roll back. This favors correctness
  and reproducibility over incremental caching; performance on very large logs
  remains to be measured before claiming it suitable for major DX contests.
- Geography and station are per-journal snapshots. Macro folders include the
  definition ID, database identity and journal number. Legacy module state and
  macro paths retain their existing behavior.
- `UdcContest` implements the contest callbacks for initialization, interface,
  navigation, scoring, export, recalculation and Call History. `BuiltinContest`
  forwards the existing module API without changing its function signatures.
  Optional hooks (`validate_contact`, `band_frequency`, `reset_inputs`,
  `key_event`, `teardown`, `macro_directory`, `on_focus_changed`) preserve builtin
  behavior when absent. The UDC 80 m SSB button selects 3650 kHz.
- Journal snapshots keep their engine version. Existing journals retain the
  original section, duplicate and digital-mode semantics; updating the application
  does not reinterpret them. Import a definition and create a new journal to use
  the current engine. Unsupported snapshot versions are refused.
- Initial journal selection is persisted during station setup; plugin activation
  waits until the main window and its docks are initialized. Later journal changes
  activate immediately through the same loading path.

## Call History

Enable **Use Call History** in **File → Configuration Settings → Options**,
then choose **File → Load Call History File**. The file uses the N1MM CSV format:
a `!!Order!!` header names the fields, followed by comma-separated records.
The extension does not determine the format. Successful import reports a row
count; invalid files leave the existing history unchanged. History belongs to
the current database.

Typing a callsign shows a hint. Tab, Space or a mouse transition into an exchange
field fills eligible empty fields according to the active journal definition.
`Exch1`, section, name and validated locator data are mapped to corresponding
exchange fields. A recognized section/district takes precedence over a geographic
fallback; incomplete values remain hints. The received serial is never guessed.

Operator-entered values are preserved. Changing the callsign clears only unchanged
values owned by the automatic suggestion. Manually editing an automatic value
transfers ownership to the operator. Portable calls such as `/P` and `/M` are
looked up separately. History state and signal handlers are released when switching
journals.

## Sections and operating time

Section lists support single spellings and two-column spelling → section mappings.
The normalized `Sect` is used for scoring, while `Exchange1` retains the entered
exchange in Cabrillo and ADIF. Each journal owns its section mappings.

**File → UDC operating / OFF times** reports full UTC clock minutes. A minute
containing a logged QSO counts as operating time. Short internal gaps remain
operating time; complete leading/trailing idle minutes count as OFF. Missing or
identical calendar endpoints require actual start/end dates. Calendar hints and
OFF reports do not impose scoring limits or change points.

## Repeat intervals and band changes

A five-part `DupeQSOMinutesAgo` rule uses the last matching recorded QSO, including
duplicates; a scalar interval uses the last credited QSO. `DupeType=4` disables
ordinary duplicate checking, but an active interval still applies. The extended
interval uses its explicit band/mode flags and fixed-session identity. With
`CompareToSecond=False`, seconds are discarded from both UTC timestamps.
The score, entry indicator and bandmap use the same repeat decision.

Band counts and hold deadlines are reconstructed from logged contacts, including
duplicates, separately for each radio. The first QSO starts a hold timer with zero
changes. A mode-only change can increment the counter without restarting the band
hold timer. Timers carry across clock-hour boundaries. Edits, deletion, imports
and restart rebuild this state. Limits produce operating warnings rather than
scoring penalties; the status bar shows counters and remaining hold time.

[INTERVAL.udc](../examples/udc/INTERVAL.udc) demonstrates repeat intervals and
band-change warnings. It is a teaching example, not an official contest definition.

## FT8 / FT4

UDC definitions with `Mode=BOTH` can receive WSJT-X logged ADIF messages. Enable
logged ADIF UDP output in WSJT-X and send it to Not1MM's receiver on port 2237,
multicast group `224.0.0.1`. The received QSO keeps the original UTC time,
frequency, locator and signed reports. An explicit `STATION_CALLSIGN` must match
the journal's station. Missing or ambiguous required exchange fields produce an
error. Repeated delivery is idempotent across journal reopen; later independent
QSOs are retained and checked under the contest rules.

Incoming QSOs preserve the operator's in-progress manual entry and refresh the
log and score. FT4 ADIF uses `MODE=MFSK`, `SUBMODE=FT4`; FT8 uses `MODE=FT8`.
Both use DG in Cabrillo. Decoder control, transmission, decode-list colouring and
manual TOUR commands are outside this support. Network access must be enabled
when running the application in a sandbox.

[FTMIX.udc](../examples/udc/FTMIX.udc) is a teaching example for mixed FT modes.
Review the actual event rules before using any definition for a contest.

## Testing and packaging

Original third-party acceptance files are kept outside the repository. See the
[external corpus setup](../test/fixtures/udc/README.md) for paths and source pins.
Corpus-dependent unit tests skip when that directory is absent; the synthetic
runtime tests are independent. Qt corpus checks require the files. Tests never
download or restore third-party payloads automatically.

Run from the repository root with the project dependencies, pytest and pytest-qt
installed:

```sh
export PYTHONPATH=.:test QT_QPA_PLATFORM=offscreen
python3 -m pytest test/test_udc_runtime_rules.py test/test_udc_call_history.py test/test_udc_engine.py test/test_udc_invariants.py test/test_udc_sections_operating.py -q
python3 test/udc_runtime_qt_smoke.py
python3 test/udc_qt_smoke.py
python3 test/udc_call_history_qt_smoke.py
```

The Qt scripts use private temporary profiles and test journals. For a source
Flatpak build, use the repository's [build script](../build_flatpak.sh) and SDK
manifest.

References: [N1MM UDC parameters](https://n1mmwp.hamdocs.com/appendices/udc-editor/),
[N1MM operating/OFF time convention](https://n1mmwp.hamdocs.com/manual-windows/entry-window/),
[WSJT-X UDP layout](https://github.com/WSJTX/wsjtx/blob/master/Network/NetworkMessage.hpp),
[ADIF mode/submode specification](https://adif.org/316/ADIF_316.htm).
