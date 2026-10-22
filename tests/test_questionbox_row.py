"""The row of questions waiting on the user in one chat
(`frontend/src/lib/questionbox.svelte.js`): the permission of a tool, the
model's own question and the questions of the agents the chat started stand
in one row, "n of N"; a question pushed away with "later" stays in the row and
keeps a chip of its own, named after whoever asks.

The module is compiled with Svelte's own compiler and run in Node against two
stand-ins (the chat state and the agents' questions), so what runs is the file
the interface imports. The bar and the card are read as source."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from tests.fensterquelle import BAR_SOURCE

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MODULE = FRONTEND / "src" / "lib" / "questionbox.svelte.js"
BAR = BAR_SOURCE
CARD = FRONTEND / "src" / "teile" / "QuestionBox.svelte"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

PREFIX = "questionbox-row"


def _run(js: str) -> dict:
    """Compile the module, run `js` against it (`w` is the module, `state` the
    chat state stand-in, `agents` the agents' questions by chat) and return
    its report."""
    driver = FRONTEND / f"{PREFIX}.driver.mjs"
    built = FRONTEND / f"{PREFIX}.built.mjs"
    state = FRONTEND / f"{PREFIX}.state.mjs"
    agents = FRONTEND / f"{PREFIX}.agents.mjs"
    state.write_text(
        "export const zustand = { werkzeugfrage: {}, benutzerfrage: {}, auftraege: [] }\n",
        encoding="utf-8",
    )
    agents.write_text(
        "export const agentList = {}\n"
        "export function agentQuestions(chatId) { return agentList[chatId] ?? [] }\n"
        "export function questionOpen(job) {\n"
        "  return Boolean(job && job.state === 'wartet' && job.question && job.question.frage)\n"
        "}\n",
        encoding="utf-8",
    )
    driver.write_text(
        textwrap.dedent(
            """
            import { compileModule } from 'svelte/compiler'
            import { readFileSync, writeFileSync } from 'fs'
            let code = compileModule(readFileSync(%r, 'utf-8'), {
              filename: 'questionbox.svelte.js', generate: 'client',
            }).js.code
            code = code.replaceAll("from './zustand.svelte.js'", "from './%s'")
            code = code.replaceAll("from './agentchat.svelte.js'", "from './%s'")
            writeFileSync(%r, code)
            const w = await import('./%s')
            const { zustand: state } = await import('./%s')
            const { agentList: agents } = await import('./%s')
            const report = await (async () => {
            %s
            })()
            console.log('---REPORT---' + JSON.stringify(report))
            """
        )
        % (
            str(MODULE), state.name, agents.name, str(built), built.name, state.name,
            agents.name, textwrap.indent(js, "  "),
        ),
        encoding="utf-8",
    )
    try:
        run = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=120
        )
    finally:
        for leftover in (driver, built, state, agents):
            leftover.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    assert "---REPORT---" in run.stdout, run.stdout[-2000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


SETUP = """
const ask = { aufruf_id: 'c1', frage: 'which?', optionen: [] }
const askAgent = (chat, id, name) => {
  agents[chat] = [...(agents[chat] ?? []), { id, agent: name, question: { aufruf_id: id + '-call', frage: 'and?' } }]
}
const shape = (standing) => standing && ({
  kind: standing.kind, position: standing.position, total: standing.total,
  name: standing.question.agentName ?? null,
})
"""


@needs_node
def test_a_question_of_the_model_pushed_away_stays_in_the_row_while_an_agent_asks():
    """The model asks and is pushed away with "later", then an agent asks: the
    row counts two, the agent stands as "2 of 2" and the model's question is
    still in the row, pushed away — it was unreachable before."""
    report = _run(
        SETUP
        + """
        state.benutzerfrage.A = ask
        const model = w.standingQuestion('A')
        w.deferQuestion('A', model)
        askAgent('A', 'job1', 'research')
        const row = w.waitingQuestions('A')
        const standing = w.standingQuestion('A')
        return {
          count: row.length,
          standing: shape(standing),
          pushed: row.filter((item) => w.isDeferred('A', item)).map((item) => item.kind),
        }
        """
    )
    assert report["count"] == 2
    assert report["standing"] == {"kind": "agent", "position": 2, "total": 2, "name": "research"}
    assert report["pushed"] == ["ask"]


@needs_node
def test_the_row_runs_permission_then_model_then_agents_and_counts_all_of_them():
    report = _run(
        SETUP
        + """
        state.werkzeugfrage.A = { aufruf_id: 't1', name: 'shell' }
        state.benutzerfrage.A = ask
        askAgent('A', 'job1', 'research')
        askAgent('A', 'job2', 'writer')
        const kinds = w.waitingQuestions('A').map((item) => [item.kind, item.position, item.total])
        const first = shape(w.standingQuestion('A'))
        w.deferQuestion('A', w.standingQuestion('A'))
        const second = shape(w.standingQuestion('A'))
        return { kinds, first, second }
        """
    )
    assert report["kinds"] == [["tool", 1, 4], ["ask", 2, 4], ["agent", 3, 4], ["agent", 4, 4]]
    assert report["first"]["kind"] == "tool" and report["first"]["position"] == 1
    assert report["second"]["kind"] == "ask" and report["second"]["position"] == 2


@needs_node
def test_every_question_pushed_away_is_in_the_row_and_the_first_one_stands_for_the_chip():
    report = _run(
        SETUP
        + """
        state.benutzerfrage.A = ask
        askAgent('A', 'job1', 'research')
        for (const item of w.waitingQuestions('A')) w.deferQuestion('A', item)
        const row = w.waitingQuestions('A')
        const standing = w.standingQuestion('A')
        const pushed = row.filter((item) => w.isDeferred('A', item)).length
        w.resumeQuestion('A', row[1])
        return {
          pushed,
          standingWhenAllPushed: shape(standing),
          standingAfterResume: shape(w.standingQuestion('A')),
          stillPushed: w.waitingQuestions('A').filter((item) => w.isDeferred('A', item)).map((item) => item.kind),
        }
        """
    )
    assert report["pushed"] == 2
    assert report["standingWhenAllPushed"]["kind"] == "ask"
    assert report["standingAfterResume"] == {"kind": "agent", "position": 2, "total": 2, "name": "research"}
    assert report["stillPushed"] == ["ask"]


@needs_node
def test_a_single_question_is_no_row_and_two_agents_count_as_before():
    """Silence probe: one question alone has a total of one (the card then
    shows its own number or the permission label); two agents and no question
    of the model count "1 of 2" and "2 of 2", as they did."""
    report = _run(
        SETUP
        + """
        state.benutzerfrage.A = ask
        const alone = shape(w.standingQuestion('A'))
        state.benutzerfrage.B = undefined
        askAgent('B', 'job1', 'research')
        askAgent('B', 'job2', 'writer')
        const row = w.waitingQuestions('B').map((item) => shape(item))
        const none = w.standingQuestion('C')
        return { alone, row, none }
        """
    )
    assert report["alone"] == {"kind": "ask", "position": 1, "total": 1, "name": None}
    assert report["row"] == [
        {"kind": "agent", "position": 1, "total": 2, "name": "research"},
        {"kind": "agent", "position": 2, "total": 2, "name": "writer"},
    ]
    assert report["none"] is None


def test_the_card_counts_any_kind_of_question_in_the_row():
    source = CARD.read_text(encoding="utf-8")
    assert "let { kind, question, position = 1, total = 1," in source
    pill = source[source.index("const pill = $derived.by"):source.index("/* A tool's arguments as pairs")]
    assert "if (total > 1) return t('question_box.agent_position', { n: position, total })" in pill
    # Alone, a permission keeps its label and a question its own number.
    assert pill.index("total > 1") < pill.index("t('werkzeug.permission_label')")
    assert "t('benutzerfrage.nummer', { zahl: question.nummer })" in pill


def test_each_question_pushed_away_has_a_chip_that_names_who_asks():
    bar = BAR.read_text(encoding="utf-8")
    assert "{#each pushedAway as item (questionKey(item))}" in bar
    chip = bar[bar.index("{#each pushedAway as item"):]
    chip = chip[:chip.index("{/each}")]
    assert 'class="later-chip"' in chip and "onclick={() => resume(item)}" in chip
    assert "{@const asker = item.kind === 'agent' ? item.question.agentName : modelName}" in chip
    assert '<span class="asker">{asker}</span>' in chip
    # The card gets the place of the question in the row.
    assert "position={standing.position}" in bar and "total={standing.total}" in bar


def test_a_chip_brings_its_question_to_the_card_and_the_one_that_stood_takes_its_place():
    bar = BAR.read_text(encoding="utf-8")
    body = bar[bar.index("function resume(item) {"):]
    body = body[:body.index("\n  }\n")]
    assert "questionKey(standing) !== questionKey(item)" in body
    assert "deferQuestion(zustand.aktiverChat, standing)" in body
    assert body.index("deferQuestion(") < body.index("resumeQuestion(zustand.aktiverChat, item)")


def test_several_chips_share_the_room_one_chip_had():
    """Silence probe for the bar: the group of chips is no wider than one chip
    was, and each chip may shrink, so a second agent asking does not push the
    model picker out of a narrow bar."""
    bar = BAR.read_text(encoding="utf-8")
    group = re.findall(r"(?m)^  \.later-chips \{(.*?)^  \}", bar, re.S)
    assert len(group) == 1
    assert "max-width: 160px" in group[0] and "min-width: 0" in group[0]
    chip = re.findall(r"(?m)^  \.later-chip \{(.*?)^  \}", bar, re.S)
    assert len(chip) == 1
    assert "flex: 0 1 auto" in chip[0] and "min-width: 0" in chip[0]
    assert "max-width: 160px" in chip[0]


# --- An agent picked in the agents column --------------------------------------

PICK = """
const job = (id, extra = {}) => ({
  id, agent: 'sucher', state: 'wartet', chat_id: null,
  question: { aufruf_id: id + '-k1', frage: 'which?' }, ...extra,
})
"""


@needs_node
def test_a_waiting_agent_without_a_chat_stands_alone_in_the_card():
    """The agent has no chat, so it has no place in the row; picking it puts
    its question in the card, with its own name, "1 of 1"."""
    report = _run(
        SETUP
        + PICK
        + """
        state.auftraege.push(job('J1'))
        const before = w.standingQuestion('A')
        const shown = w.showAgentQuestion('A', state.auftraege[0])
        const standing = w.standingQuestion('A')
        const noChat = (() => {
          // No chat open, an agent without a chat: the one the card must show.
          w.showAgentQuestion(null, state.auftraege[0])
          return shape(w.standingQuestion(null))
        })()
        return {
          before, shown, noChat, row: w.waitingQuestions('A').length,
          standing: shape(standing), jobId: standing.question.jobId,
          callId: standing.question.aufrufId, key: w.questionKey(standing),
        }
        """
    )
    assert report["before"] is None and report["shown"] is True
    assert report["noChat"] == {"kind": "agent", "position": 1, "total": 1, "name": "sucher"}
    assert report["row"] == 0
    assert report["standing"] == {"kind": "agent", "position": 1, "total": 1, "name": "sucher"}
    assert report["jobId"] == "J1" and report["callId"] == "J1-k1"
    assert report["key"] == "agent:J1:J1-k1"


@needs_node
def test_later_takes_the_picked_question_away_and_a_second_pick_brings_it_back():
    report = _run(
        SETUP
        + PICK
        + """
        state.auftraege.push(job('J1', { chat_id: 'other' }))
        w.showAgentQuestion('A', state.auftraege[0])
        const first = w.standingQuestion('A')
        w.deferQuestion('A', first)
        const afterLater = w.standingQuestion('A')
        w.showAgentQuestion('A', state.auftraege[0])
        return { first: shape(first), afterLater, again: shape(w.standingQuestion('A')) }
        """
    )
    assert report["first"] == {"kind": "agent", "position": 1, "total": 1, "name": "sucher"}
    assert report["afterLater"] is None
    assert report["again"] == report["first"]


@needs_node
def test_a_picked_question_does_not_hide_the_row_of_the_chat_once_pushed_away():
    report = _run(
        SETUP
        + PICK
        + """
        state.benutzerfrage.A = ask
        state.auftraege.push(job('J1', { chat_id: 'other' }))
        w.showAgentQuestion('A', state.auftraege[0])
        const picked = shape(w.standingQuestion('A'))
        w.deferQuestion('A', w.standingQuestion('A'))
        return { picked, row: shape(w.standingQuestion('A')) }
        """
    )
    # It counts the question waiting behind it: "1 of 2", not "1 of 1".
    assert report["picked"]["name"] == "sucher" and report["picked"]["total"] == 2
    assert report["row"] == {"kind": "ask", "position": 1, "total": 1, "name": None}


@needs_node
def test_picking_an_agent_of_the_row_brings_it_to_the_front_and_pushes_the_rest_back():
    report = _run(
        SETUP
        + PICK
        + """
        state.benutzerfrage.A = ask
        agents.A = [job('J1', { chat_id: 'A' }), job('J2', { chat_id: 'A', agent: 'writer' })]
        state.auftraege.push(...agents.A)
        const shown = w.showAgentQuestion('A', agents.A[1])
        const standing = shape(w.standingQuestion('A'))
        const pushed = w.waitingQuestions('A').filter((i) => w.isDeferred('A', i)).map((i) => i.kind + ':' + (i.question.agentName ?? ''))
        return { shown, standing, pushed }
        """
    )
    assert report["shown"] is True
    assert report["standing"] == {"kind": "agent", "position": 3, "total": 3, "name": "writer"}
    assert report["pushed"] == ["ask:", "agent:sucher"]


@needs_node
def test_an_agent_that_does_not_wait_opens_no_card():
    """Silence probe: a click on a run that is not waiting shows nothing."""
    report = _run(
        SETUP
        + PICK
        + """
        state.auftraege.push(job('J1', { state: 'laeuft' }))
        const shown = w.showAgentQuestion('A', state.auftraege[0])
        return { shown, standing: w.standingQuestion('A') }
        """
    )
    assert report["shown"] is False and report["standing"] is None


@needs_node
def test_a_picked_question_stays_in_its_chat_and_the_next_question_of_the_agent_does_not_stand_up():
    report = _run(
        SETUP
        + PICK
        + """
        state.auftraege.push(job('J1'))
        w.showAgentQuestion('A', state.auftraege[0])
        const inOtherChat = w.standingQuestion('B')
        state.auftraege[0] = job('J1', { question: { aufruf_id: 'J1-k2', frage: 'and then?' } })
        return { inOtherChat, next: w.standingQuestion('A') }
        """
    )
    assert report["inOtherChat"] is None
    assert report["next"] is None


def test_the_bar_shows_the_picked_question_and_a_click_in_the_column_asks_for_it():
    bar = BAR.read_text(encoding="utf-8")
    assert "standingWith(zustand.aktiverChat, waiting)" in bar
    column = (FRONTEND / "src" / "teile" / "ModulAgenten.svelte").read_text(encoding="utf-8")
    assert "showAgentQuestion(zustand.aktiverChat, auftrag)" in column
    # The old box, its band and its sentence are gone: the question is
    # answered in the card only.
    for gone in ("Benutzerfrage", "wartebanner", "wartefrage", "warteweg", "frage_nach_neustart"):
        assert gone not in column
    assert not (FRONTEND / "src" / "teile" / "Benutzerfrage.svelte").exists()
    for locale in ("de", "en"):
        texts = json.loads((ROOT / "app" / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        assert "frage_nach_neustart" not in texts["jobs"]
        assert "banner" in texts["jobs"]


@needs_node
def test_the_card_stands_for_a_question_and_not_for_one_pushed_away():
    report = _run(
        SETUP
        + """
        const out = { none: w.questionCardStands('A') }
        state.benutzerfrage.A = ask
        out.asked = w.questionCardStands('A')
        out.other_chat = w.questionCardStands('B')
        w.deferQuestion('A', w.standingQuestion('A'))
        out.pushed_away = w.questionCardStands('A')
        w.resumeQuestion('A', w.standingQuestion('A'))
        out.brought_back = w.questionCardStands('A')
        return out
        """
    )
    assert report == {
        "none": False,
        "asked": True,
        "other_chat": False,
        "pushed_away": False,
        "brought_back": True,
    }


@needs_node
def test_a_second_question_stands_up_when_the_first_is_pushed_away():
    report = _run(
        SETUP
        + """
        state.benutzerfrage.A = ask
        w.deferQuestion('A', w.standingQuestion('A'))
        askAgent('A', 'job1', 'research')
        return { stands: w.questionCardStands('A') }
        """
    )
    assert report == {"stands": True}
