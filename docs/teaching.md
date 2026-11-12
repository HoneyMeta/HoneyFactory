# Teaching

HoneyFactory can be used as a training system for vocational schools, universities and in-company training: PLC
programming on simulated machines, troubleshooting, production-line operation and optimisation, and MES basics.
Teachers and students use the same web UI (or the desktop client); students see a reduced interface with the
teaching workspace and the panels their lesson needs.


## Roles and pages

| Role | Page | Content |
|---|---|---|
| Student | **Courses** (`/courses`) | course cards, course details, the current lesson (brief, answer, result), school assignments |
| Teacher, administrator | **Courses** (`/courses`) | my courses, course library, course editor, preview as a student, publish to a class |
| Teacher, administrator | **Teaching** (`/teach`) | teaching console (submissions, review, AI suggestions), classes and rosters, assignments |
| Teacher | **Class progress** (`/progress`) | who is online, stuck, working, not started or done; current lesson and step of every student |

Demo data: start the server with `VF_DEMO=1`, or click **Create demo class** in the teaching console. The demo
teacher is `demo_teacher` / `teach123`, the students `demo_s01` … `demo_s06` / `123456`. Students and teachers who log
in with an initial password must change it.

## Built-in courses

| Course | Level | Lessons |
|---|---|---|
| Factory and Equipment Basics | 1 | 5 (production-line tasks, one diagnosis) |
| Sensors and Actuators (PLC prerequisite) | 1 | 5 |
| PLC Control Basics | 1 | 15 PLC exercises, from a motor latch to a full line |
| Production Operations Basics | 2 | 5 |
| Production Line Simulation and Optimization (Machining) | 2 | 8 |
| MES Basics | 2 | 4 MES tasks (teaching MES) |
| Foundry Operations (Comprehensive) | 3 | 6 (production-line tasks, one diagnosis) |

Courses live in `vfactory/courses/*.json`, the plants they use in `vfactory/courses/plants/`, the PLC training scenes
in `vfactory/control/scenes/*.json`. English texts are kept in `i18n/*.en.json` next to each file
(see `docs/translating-content.md`). Lessons unlock in order; a teacher can open all of them for a class.

## Lesson types

| Type | `kind` | The teacher sets | Grading |
|---|---|---|---|
| PLC exercise | `cell` | scene, lock the model, which rubric items of the scene count, extra checks ("press START at t, output Y within s seconds") | automatic test sequence of the scene (`vfactory/control/scoring.py`); the live checklist uses the same conditions |
| Production-line task | `plant` | plant template, preset parameters, which parameters students may change, whether devices may be added or removed, simulated hours, seed, warm-up | `kpi`, `budget` and `limit` rules, evaluated on a run with a fixed seed |
| Fault diagnosis | `diagnose` | plant and the parameters to break at the start (`faults`) | the student points at the device and the fault type on the diagram, then fixes it |
| Quiz | `quiz` | single and multiple choice, true/false, numeric with tolerance and unit | `answer` rules, no sandbox |
| Point at the device | `point` | plant template, questions whose answers are device ids | `answer` + `pick` |
| MES task | `mes` | declarative checks on the teaching MES (`query`, `op`, `value`) | queries registered by the teaching MES (`vfactory/mes/teach_rules.py`) |

Unlocking per lesson (`unlock`): `{min: 60}` pass mark, `{after: [lesson ids]}` prerequisites, `{free: true}` always
open. Without it the next lesson unlocks when the previous one is passed.

Grading cannot be gamed from the browser: the server re-runs the student's model or program, production-line tasks
check that the student stayed within the allowed changes, and answers are sealed in the course package.

## Course editor

Teachers build and change courses in the course editor (outline of chapters and lessons on the left, the selected
item on the right). A **check** runs every lesson's starting model (should score low) and the reference solution
(should score full marks). **Preview as a student** opens the lesson in a sandbox. Publishing freezes a version;
the course package is signed (`vfactory/courses/coursepkg.py`), and the signing key is generated per installation and
stored in its database.

## Classes and assignments

- Classes, roster import (paste from Excel, CSV, with or without a header, preview before import, `.xlsx` upload),
  bulk password reset, moving students between classes.
- Publish a course or single lessons to a class, with start time, deadline, maximum attempts and late submissions.
- One sandbox per student and assignment (`sb-<user>-<assignment>`). Sandboxes sleep after `VF_SANDBOX_IDLE_S`
  seconds without a viewer and at most `VF_SANDBOX_MAX_ACTIVE` run at once. Looking at a student's work does not wake
  the sandbox.
- Submissions keep the program snapshot and a replay of the grading; the teacher can review and change scores per
  rubric item with comments, inject a fault into a student's sandbox for a troubleshooting exercise, watch read-only
  or take over, and export the grade book.
- Homework from desktop clients arrives as `.vfhw` packages (program, model, answers). A self-hosted server grades the
  package again and ignores the score the client reported; see [desktop-client.md](desktop-client.md).

## AI tutor and AI grading

- The **AI tutor** (the assistant panel for student accounts) sees the lesson, the student's program or model and the
  live sandbox, gives hints and "look here" pointers to the checklist, log, buttons, ladder elements or devices, and
  never gives the solution. Without a model it falls back to the hints written into the lesson.
- **AI grading** suggests scores and comments for open answers and explains failed rubric items; the teacher accepts
  or changes them.
- Both need a configured model (see the README, *AI configuration*). The teacher decides per assignment whether the
  tutor is available.

## Teaching MES

`vfmes/` is a plain MES for teaching (no AI features): work orders, scheduling (Gantt), dispatch, automatic and manual
production reporting, material issue and return, serial numbers per part, andon; inspection templates, incoming /
in-process / first-article / final inspection, nonconformance handling, SPC (X̄-R, rules, Cpk), 8D; equipment
register, live monitor, OEE with downtime timeline, maintenance; inventory, AGV tasks, shipping; energy; foundry heat
and nodularising records, NC programs and tool life; dashboards for the shop floor and phones.

It runs only on the student's PC, started on demand by the desktop client for one local plant, and receives the plant's
data by the point-table addresses like a real MES would. MES lessons query its state for grading. The intelligent
MOM/MES product is [HoneyMOM](https://github.com/HoneyMeta/HoneyMOM); the teaching MES does not depend on it. The
module structure of the teaching MES was designed with reference to the open-source ktg-mes (see
[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md)). Details: [vfmes/README.md](../vfmes/README.md) (Chinese).

## Checks

`tests/teach_check.py`, `teach_audit_check.py`, `course_check.py` (`--offline` without a server),
`courses_check.py`, `package_check.py`, `coach_overlay_check.py`, `tutor_point_check.py`, `mes_edu_check.py`; browser
walk-throughs `teach_ui.js`, `courses_ui.js`, `basic_courses_ui.js`, `mes_edu_ui.js`.
