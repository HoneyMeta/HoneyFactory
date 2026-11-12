# Backend i18n: messages, content, server language

HoneyFactory is English by default and switchable to Simplified Chinese (zh-CN). The product was written in Chinese, so the
Chinese source text is the message id everywhere. Same approach as HoneyMOM (`honeymom/i18n.py`).

## Request language

`vfactory/i18n.py` resolves the language of every request (HTTP and WebSocket):

1. header `X-Lang: en | zh-CN` (also `zh`, `zh_CN`),
2. query `?lang=en | zh-CN` (downloads, `window.open`, `<img src>`, the WebSocket URL),
3. `Accept-Language` (first tag `zh*` -> zh-CN, else en),
4. the server language: env `VF_LANG` (default `en`).

The response header `Content-Language` echoes it. The teaching MES (`vfmes/`, a separate process started by the desktop client)
uses the same module and catalogue; the client's `/api/mes/...` proxy forwards the page's `X-Lang`.

`loop.run_in_executor(...)` carries the request language into worker threads (patched in `i18n.install`), so texts made in threads
(model calls, experiments, forks) use it too.

## Messages (Python code)

- `_tr('原文 {name}', name=x)` translates a message into the current language (`vfactory/locale/en.json`, optional overrides in
  `vfactory/locale/zh-CN.json`); placeholders are named `str.format` fields. Values passed as placeholders that are catalogue texts
  (labels from module-level tables) are translated too.
- Module-level tables (block catalogues, label dicts, enum labels) keep the source text: they are translated where they are served:
  English JSON responses under `/api/` translate every string value that is exactly a catalogue id or a mapped content text
  (`i18n.FILTER_SKIP` keys such as `id`, `code`, `kind`, `status`, `state`, `cls`, `tag` are never touched). Endpoints whose data is
  edited and saved back (model editor, PLC programs, course drafts, ...) are not filtered (`i18n.NO_FILTER*`).
  `i18n.label(s)` translates one table label in code (exports, reports).
- **Never compare display text in logic.** Compare codes. Where old data or other processes may hold either language, use
  `i18n.variants(msgid)` (source + English) or `i18n.matches(text, msgid)` (placeholders match anything).
  Codes the frontend uses instead of texts: model issues `cat_code`, teaching progress `state_code` / `counts_code`, cell console
  entries `code` (`press`, `release`, `set`, `download`), plant areas `kind` (`melting`, `molding`, ...), workers `lead`.
- AI: every model call (`copilot.chat`) gets `i18n.llm_instruction()` after the system prompts: answer in the UI language, keep
  ids, tag names and addresses.
- `tests/i18n_check.py` fails on new Chinese literals that are neither in the catalogue nor allowlisted
  (`tests/i18n_allowlist.json`, with a reason per entry: input parsing, data contracts such as the delivery package for HoneyMOM).

Adding a message: write `_tr('中文原文')` (or English source text: an English id needs no catalogue entry), then add the English
to `vfactory/locale/en.json` and run `python tests/i18n_check.py`.

## Content (courses, PLC scenes, tours, templates, plants, samples)

Content is authored in one language (the built-in content in Chinese). The English strings live in a **string map next to the file**:

    vfactory/courses/machining.json                ->  vfactory/courses/i18n/machining.en.json
    vfactory/courses/plants/mc06_orders.yaml       ->  vfactory/courses/plants/i18n/mc06_orders.en.json
    vfactory/control/scenes/s01_motor_latch.json   ->  vfactory/control/scenes/i18n/s01_motor_latch.en.json
    vfactory/teach/tours/s01_motor_latch.json      ->  vfactory/teach/tours/i18n/s01_motor_latch.en.json
    templates/showcase.yaml, templates/cells/*.yaml, plants/*.yaml, vfactory/samples/*.json  ->  <same dir>/i18n/<name>.en.json

A map is a flat JSON object `{"<source text>": "<English>"}`. Structure (rules, parameters, answers, ids, PLC programs) exists once,
in the original file, so grading is identical in both languages; a changed source text simply falls back to the source language
until its map entry is updated. Values under `i18n.CONTENT_SKIP` keys (`id`, `key`, `type`, `source`, `program`, `st`, `expr`,
`cond`, ...) are never translated: they are identifiers and code. Tag names, block ids and protocol addresses never change (they are
data contracts with HoneyMOM and its replayer over MQTT / OPC UA / Modbus); only display names and descriptions are translated.

Where it is applied:

- courses (`courses._load`), PLC scenes (`control.scenes.get_scene`, `teach.scenes.load_scene`), tours (`teach.coach.load_tour`):
  in the request language;
- templates: in the language of the user who creates a plant from them (the new plant file is written in that language);
- plants: `server.read_plant()` reads a plant in the **server language** (`VF_LANG`) - the running simulation, its event texts and
  the MQTT / OPC UA descriptions have one language (simulation steps run under `i18n.server_language()`, also when a request
  triggers them; data written once for everybody uses `i18n.server_tr`). A plant saved from the editor keeps the texts it was saved with.
  Tag values (e.g. the machining step names on `Production/ActiveProgram/Step`) are protocol data and are not translated.
  The first-run demo plant is written in the server language.

Workflow for authors:

1. write or change the content file (or regenerate it with its builder, `vfactory/courses/build*.py` / `vfactory/control/scenes/build.py`);
2. `python tools/i18n_maps.py --sync` adds the new texts to the maps with an empty translation (and drops stale ones);
3. fill in the English (by hand or machine translation, then review) and run `python tests/i18n_check.py`.

Content written directly in English needs no map. A map for another language would be `<name>.<lang>.json` (only `en` is wired now).

## Demo and production

- Production (default): a fresh server has **no accounts**. `GET /api/setup/admin` (no login) -> `{needed, demo, lang}`;
  `POST /api/setup/admin {username, password, name}` creates the first administrator (password >= 8 characters, not one of the
  well-known initial passwords) and returns `{token, user}` like `/api/login`. Only while no active administrator exists.
  CLI: `python -m vfactory create-admin [--username U --password P --name N]`. `/api/health` reports `lang`, `langs`, `demo`, `setup_needed`.
- Demo: `VF_DEMO=1` creates the demo accounts `admin` / `engineer` / `guest` (password `honey123`) on a fresh database and the demo
  class (`demo_teacher` / `teach123`, students `demo_s01..06` / `123456`). The test suites run against a demo server.
- SaaS (`VF_MODE=saas`) never creates demo accounts (organisations and accounts come from the operations console).
- The desktop client keeps its own local account (no first-run step).
- Existing databases are not changed (their accounts stay as they are).

## Tests

- `python tests/i18n_check.py` - backend catalogue / content coverage.
- Python suites assert Chinese texts: they import `tests/i18n_pin.py`, which adds `X-Lang: zh-CN` (or `VF_TEST_LANG`) to every
  request and sets `VF_LANG` for code run inside the test process. Run them against a demo server (`VF_DEMO=1`), with the server in
  either language (`VF_LANG=zh-CN` or `en`).
