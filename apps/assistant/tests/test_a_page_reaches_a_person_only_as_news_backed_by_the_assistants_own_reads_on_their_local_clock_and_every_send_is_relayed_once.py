"""A page reaches a person only when it is news, carries only what the assistant's own reads back, is written on that person's local clock, and every send is remembered and relayed once.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A covering page triage reads off the awareness rows is one the claim gate can find.

WHAT IT PINS. `core.awareness.render` and `core.triage.triage`, across their
public interfaces, with the alerts table seeded through `state.record_alert`.
A silence that names another alert's page as `covered_by_fingerprint` stands
only when that fingerprint delivered, and the gate checks it by an exact match.
The awareness rows are the only place in triage's prompt that carries another
alert's fingerprint, so the fingerprint the model copies from them has to be
one the gate can find.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The fixture has
two fingerprints of one alert name: textfile, recorded once with
`signal_sent=True` (delivered, decision `released`), and gate-full-audit, never
delivered. The test plays the model: it reads the fingerprint printed on the
`released` row of the rendered awareness picture, exactly as the model would,
and names it as the covering page. Since textfile really delivered, the
silence on gate-full-audit must stand.

A critical page leaves through quiet hours and the morning gate while a warning waits.

WHAT IT PINS. `core.page_hold.release`, the one wire in front of the phone,
across its public interface: pages go in through `state.hold_page` with the
severity `gates/app._hold_page` copies off the alert, arrivals through
`state.record_alert` in the order `gates/app` writes them, and what comes back
is the text that reached the phone. At 02:00 and at 07:45 local a critical
page leaves at once and alone; the warning held beside it waits for 08:00. A
critical whose alert resolved before the pass is still dropped.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The paging rule,
applied by reading each case: the default quiet window is
22:00-07:30 and the morning gate holds until 08:00, so 02:00 and 07:45 are both
held moments and 08:00 is not; a critical goes through either hold, anything
else does not. Whether a page reached the phone is read off the list standing in
for the phone.

A failing Signal send backs off instead of retrying every pass.

WHAT IT PINS. `core.page_hold.release`, the only retrying sender in front of
the phone, across its public interface: a page goes in through
`state.hold_page`, the flusher's 30-second passes are calls to `release`, and
what Signal was asked to send is read off the list standing in for it. After a
failed send the next try waits 30 seconds, doubling to 15 minutes; the message
that finally lands opens with a line saying it is late and why, and the next
outage starts again from 30 seconds.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Twenty minutes
of passes, one every 30 seconds, with Signal refusing everything. Waits of 30,
60, 120, 240, 480 and 900 seconds put the tries at 0, 30, 90, 210, 450 and 930
seconds, and the next at 1830 is past the end: six sends and six not-delivered
rows, where retrying every pass is forty-one of each.

A filed mute holds for every spelling of its subject.

WHAT IT PINS. The filed mute across its three users: `state.record_filed`,
`state.filed_issue_for` and `state.clear_filed` (the table), the notify pen's
split of a batch into what may page and what is already on the board
(`notify_flush._split_silenced`), and the recurring filer
(`recurring_alerts.file_recurring_observations`). A subject is one mute whether
the sender put a severity marker or the product banner in front of it, and a
`must_page` marking no longer walks past a card that is on the board.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Every spelling
below is the same sentence with furniture in front of it, written out by hand:
the bare text, the text after a red circle, and the text after a red circle and
"[the project] ". The answer for each is read off that: same sentence, same mute.
The filer case is a fortnight of rows written by hand, three days bare and one
day marked red, so the subject was critical in one of its spellings and must
never be filed whatever the count says.

A held page that is no longer news never reaches the phone.

WHAT IT PINS. `core.page_hold.release`, the single wire in front of both of
The assistant's roads to a phone, across its public interface: pages go into the queue
through `state.hold_page`, arrivals through `state.record_alert` in the order
`gates/app` writes them (the page is held, then its own arrival is audited), and
what comes back is the text that reached the phone. A keyed page whose alert
resolved before it left is dropped, and so is a second page in one firing
episode. A flap, a page saying the thing came back, a new episode after a
resolve and a keyless page all still go.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is a
short history on one fingerprint written out by hand, and the rule applied to it
by reading it: the newest arrival after the hold is a resolve (and the page's
own arrival was not) means the page is stale; a delivered page on the key with
no resolve after it means this episode was already said. Whether a page reached
the phone is read off the list standing in for the phone.

A held page the morning brief names is not sent again, and one it leaves out still is.

WHAT IT PINS. `core.page_hold.release`, the one wire in front of the phone,
across its public interface: pages go in through `state.hold_page`, the brief
lands as the row `message_teammate` writes after a delivered send (a
`teammate-self` chat turn to the page recipient), and what comes back is the
text that reached the phone. On a weekday the night waits past 08:00 for the
brief; once the brief has landed, a page it names is stamped released and
never sent, and a page it does not name leaves on its own. With no brief, the
night leaves when the wait runs out; on a Saturday it leaves at 08:00. The
pen's night page is queued under its batch's subjects and is carried only when
the brief names every one.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The owner's rule
 (held pages go in the morning report) plus the rule that
no page is ever lost, applied by reading each case: the brief text below
names "TargetDown" and not "ResourceHigh", so only the second may
reach the phone. 23 October 2026 is a Friday and 24 October a Saturday, both
on summer time, so 08:00 local is 06:00 UTC. The default wait is 30
minutes, so 08:15 still waits and 08:30 does not.

A lifted or lapsed mute is never refiled from the occurrences it already decided.

WHAT IT PINS. `core.recurring_alerts.file_recurring_observations` with the
filed-mute table behind it (`state.record_filed`, `state.clear_filed`): a
subject the filer carded, whose card was then lifted or has lapsed, is filed
again only on occurrences that arrived after that decision, never on the same
fortnight of rows that produced the first card.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The audit rows
are written out by hand: one subject on three separate days before the
decision, and in the last case three more separate days after it. The filer's
own bar is three distinct days, so before the lift the subject qualifies once,
after the lift it has zero new days, and with three new days it qualifies once
more. The issue numbers are the ones the stubbed GitHub hands back, counted.

A page never ends on the lead-in of a fix step whose command was stripped.

WHAT IT PINS. Two halves of one road, across their public interfaces. First,
`core.signal_text.strip_markdown`, the last seam before Signal: when it drops a
command for the reader to run, it drops the whole fix step with it, the line
that introduced the command ("To un-stall it:") and the "Then ..." that
continued it, and it never leaves a double blank gap where a line was. Second,
`core.triage.triage`: the alert the model is shown carries no `first_action`
annotation, because that annotation is an ssh command written for a person at
a terminal and the model would write its draft around it.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Every draft
below is the shape a held page has before the strip, and the expected text is what a person
reading it would keep: the sentences that say what is wrong, nothing that only
pointed at a command. The chat-shaped case is a plain answer with a list and no
command, and the expected answer is the input unchanged, because the fix may not
touch a message that had nothing stripped.

A page never hands the reader a unit nobody read or a repair nothing backs.

WHAT IT PINS. `core.triage.triage` and `core.voice.render`, across their
public interfaces, with the model stubbed. The backup alert's pointer to
its evidence reaches the model; a draft naming a unit neither the alert nor a
tool result named, or asking for a state change nothing read backs, is nudged
once and then loses those sentences, while a hyphenated English word before
"service" is not taken for a unit; and the container's voice no longer teaches
"I can't read it from here".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The alert's
annotations are read from operational-rules.yml as Prometheus would render
them. The drafts are two pages of the shape the model wrote; whether
"backup-index-push" or "restarted" is backed is read off the alert payload and
the (empty) reads by eye.

A page that page_hold dropped never reads as sent in the current picture.

WHAT IT PINS. `core.awareness.render`, the block every model loop reads its
recent alerts from, across its public interface, with the tables seeded through
`state.hold_page`, `state.record_alert` and `state.mark_dropped` in the order
`gates/app` and `core/page_hold` write them. An arrival row whose decision was a
page says what became of that page: held, sent, dropped with its reason, or
never queued.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is
one arrival on its own fingerprint, and what happened to its page is written
by the fixture itself: dropped with an already-paged reason, left waiting, or
never held.

A pen silence names the card or suppression that held it.

WHAT IT PINS. `core.notify_flush.flush_pen` across its public seams: pings go
in through `state.enqueue_ping`, the mutes through `state.record_filed` and
`state.add_suppression`, and the answer is read off the `alerts` row the flush
writes. When the pen drops a ping because its subject is filed or suppressed,
that row says which card or which human suppression held it, not only how many
pings there were.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Two pings,
written by hand: the reverted-on-main ping whose
subject was filed as an issue, and an auth-journey probe failure filed as an issue.
Both cards are the test's own inserts, so the row must name an issue and an issue. A
third run holds one ping under a suppression whose reason is the test's own
sentence, so the row must carry that sentence.

A ping a closed card still mutes is reported in the brief, and the mute is not lifted.

WHAT IT PINS. `core.closed_card_mutes.report`, read by the brief through the
`my_actions` door: for every filed card GitHub answers CLOSED, one line with
the subject it still mutes and what it silenced since the last brief; an open
card says nothing; GitHub is asked once for all cards, and not again inside
the cache; and the mute itself still stands afterwards.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Three cards
written out by hand, shaped like real rows: #41 closed and
holding two revert pings (one spelled with the red marker the sender adds,
which the card was not filed under), #42 closed with nothing since the last
brief, #43 open with a ping of its own. GitHub's answer is the JSON a
GraphQL query with one alias per number returns. The newest #41 ping
arrived 04:12 UTC on Friday 16 October 2026, and local is UTC+2 that day,
so the line says Fri 06:12 local.

A resolve of a paged alert sends an all-clear, even inside the dedup window.

WHAT IT PINS. `core.triage.triage` and `core.page_hold.release`, across their
public interfaces, with the tables written through `state.record_alert` and
`state.hold_page` in the order `gates/app` writes them. A resolve whose firing
episode reached a phone is answered in code with an all-clear and no model
call; a resolve of a firing nobody heard about stays silent. The all-clear's
own delivery does not count as a page of the next firing episode.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Whether the
episode was paged is read off which rows the fixture recorded with
`signal_sent=True`; what reached the phone is the list standing in for it.

Two secret-scan pings on two commits are two findings, and each page names
its commit.

WHAT IT PINS. `core.page_render`, through `licenses_aspect` and `render` over
every selection a batch licenses, fed by `core.ping_facts.bundle`. The pen
counts history by subject, and the scan sends one fixed subject once per
commit, so a second ping on that subject is always another commit. A page that
calls it "Second time on this subject" and names no commit makes two leaks
read as one.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The two rows are
two synthetic pen rows in the stored row shape: two commits,
1111111 and 2222222, the second paged as a repeat of the first. The history
stub says the subject was seen twice before. The
expected commits are read off each row's own `SHA:` line by eye. The control is
a gate-red page with the same history, which is a real repeat of one subject
and must keep both its escalation and its rule of printing no sha.

A send from outside the recipient's session is in the relay feed once, with the number that keys their session.

WHAT IT PINS. `core.sent_feed.sends_after`, the read behind `GET /relay/sent`,
over the `chat_turns` rows the send roads write: `outbound.remember_sent` for a
page, and `state.append_chat_turn` with the loop `message_teammate` records for
a send booked to the assistant (the brief) and for one a person asked for in a chat.

WHY IT EXISTS. The brief runs in an isolated cron session, so a "Yes" to a
question the brief asked can be read as an answer to something else. The VM
relay copies this feed into the recipient's own session. Since
each person has their own session, a message a teammate asked the assistant to
send another leaves from the asker's session, so the recipient's session never
saw it and it has to be relayed too. The relay keys the session by the number the send went to.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Fixed by what
was sent, not by the feed: the brief's question, the night page and the message
A teammate's request produced all went to the owner from outside the owner's session, so all
three come back, oldest first, naming the owner and their number; and past the last id
returned nothing comes back again.

A silence that names its cover only in prose is asked once for it before it
becomes a raw page.

WHAT IT PINS. `core.triage.triage` and `core.page_hold.release`, across their
public interfaces, with the tables seeded through `state.record_alert` and
`state.hold_page`. A silence that claims an earlier page without naming a
delivered one is answered once with the pages that went out or are queued since
the alert began, and stands if the model then names one. With nothing to name it
pages at once. A queued cover takes the silenced fingerprint along when it is
released. A raw page does not stop the checked page written after it. A silence
whose own page is still queued stands, and a page written in answer to the cover
question gets the same draft checks as a first draft.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The fixture is
two alerts: a1b2c3d4e5f60718 delivered, 0f1e2d3c4b5a6978 only ever
silent. Whether a page was delivered is read off which rows were recorded with
`signal_sent=True`. The model stub names the cover only if the corrective turn
it is shown contains that fingerprint, which is what a model reading it can do.

A standing fault paged long ago is paged again when triage drafts a new page.

WHAT IT PINS. `core.page_hold.release`, the wire in front of the phone, across
its public interface: pages go in through `state.hold_page`, arrivals through
`state.record_alert` in the order `gates/app` writes them, and what comes back
is the text that reached the phone. Inside one firing episode a second page is
dropped only while the last delivery on its fingerprint is younger than the
window the triage prompt tells the model about; after that it is news again.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. One fingerprint
that fires and never resolves, written out by hand: a first page that lands, a
second draft an hour before the window ends (so Alertmanager's four-hourly
re-send folds away), and a third draft an hour after it (so it goes). The
window is read out of the sentence `core.triage` puts in front of the model,
not from the constant, so a prompt and a mechanism that disagree fail here.
Whether a page landed is read off the list standing in for the phone.

A triage page never cites an issue or a past incident its own reads did not
back.

WHAT IT PINS. `core.triage.triage` and `core.claims.unread_issue_numbers`,
across their public interfaces, with the model and the tools stubbed. An issue
spelled out as "issue 42" counts as a citation; a page citing one no reading
of the pass carried, or diagnosing by analogy to a past incident ("Same pattern
as the earlier incidents") that the reads do not show, is nudged once and then
loses those sentences. A reading that does carry the issue keeps it.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The one reading
is a kubectl events text written here, with no issue number and
no word of the analogy in it; the control reading is gh_issue_view output
carrying "number: 42". Which sentence is backed is read off those by eye.

A triage pass stores what it read beside what it said, and a critical
silence on an unread stamp pages.

WHAT IT PINS. `core.triage.triage` across its public interface, with the tools
and the model stubbed and the readings read back through
`state.message_evidence.said_between`. A pass that ran the model leaves one
row on the loop `triage`, keyed by the alert's fingerprint, holding its
readings and its draft or its reason for silence. A silence on a critical whose
reason carries a date, time or number that no reading of the pass contains
becomes a raw page.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The one tool
call returns a fixed text the test wrote, so whether "6f6f6f6f" or "13:55" is
in any reading is read off that text and the alert payload by eye: in the
first case neither is, in the second the reading carries both.

A triage silence never cites a page its fingerprint never delivered.

WHAT IT PINS. `core.triage.triage` and `core.awareness.render`, across their
public interfaces, with the alerts table seeded through `state.record_alert`.
A silence whose reason claims a page ("already paged and delivered at 13:40")
stands only when the table shows a delivered page on this fingerprint, or on
the fingerprint the model named as the covering page; otherwise it becomes a
raw page. The model is told this fingerprint's own page history, read by
code, and the awareness rows say which fingerprint each line is about.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The fixture is
two fingerprints of one alert name: A, textfile,
one row with `signal_sent_at` set; B, gate-full-audit, only silent rows with
`signal_sent_at` NULL. Whether a page was delivered is read off the fixture by
looking at which rows were recorded with `signal_sent=True`, and nothing else.
The time the model claims, 03:17 UTC, is chosen so that it is never the time
the table holds: code renders a delivery as `YYYY-MM-DDTHH:MMZ`, never with
" UTC" after it.

A triage silence reason keeps its clock times, and its counts come from the
table.

WHAT IT PINS. `core.triage.triage` across its public interface, with the model
stubbed and the alerts table seeded through `state.record_alert`. A silence
that stands is stored with the model's words as they came, after the time code
read. The page history the model is shown gives the delivery in local time
and how many judged silences followed it, counted by code.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The delivery
is pinned at 2026-06-11T19:14Z, which is 21:14 in local under CEST. After
it the fixture writes three judged silences and one dedup-window hit, which is
mechanical and not a judgement: three.

An all-clear says the alert stopped firing and when, and never that the
problem is gone.

WHAT IT PINS. `core.triage.triage` across its public interface, with the firing
row written through `state.record_alert` as `gates/app` writes it. A resolve of
a paged alert is answered in code; this pins the words of that answer.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A Prometheus
resolve means only that the rule's expression stopped returning the series, and
that also happens when the subject of the series is deleted. The
notulen-waiting rule matches a Pending pod, so releasing the container resolves it
while the meeting is still untranscribed. The draft therefore may
not carry any claim that the problem is over ("needs no action", "cleared",
"fixed", "resolved", "back to normal"). The clock it must name is the alert's
end, 2030-07-10 16:41 UTC, which is 18:41 in local summer time (UTC+2).

The weekly compact sees the commits of its window, and is told to keep a note's hedge.

WHAT IT PINS. `compact.compact_week`, at its public seam: what reaches the
summariser holds the commits GitHub has for the window next to the journal
notes, and its instructions keep a source's hedge, copy times exactly and only
say "no resolution" after checking the commits. The window's bound reaches
GitHub as UTC with a Z (a "+00:00" in a query string is read as a space), with
a page of up to 99 commits rather than a report's 40.  

WHY IT EXISTS. A compact that sees only notes and chat can write "no
resolution recorded" for a page that a commit fixed within the hour, and can
turn a patrol's hedged "likely a billing-period reset artifact" into a flat
"(artifact, fine)".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The commit sha
is the real fix, fed through the GitHub seam `changes._run_gh`, so it must
appear in what the summariser reads.

Triage names the worklist item a page concerns only from the open items its prompt shows it.

WHAT IT PINS. `core.triage.triage` across its public interface: an alert goes
in, the model behind `core.brain.run` sees the user turn triage built, and the
`TriageResult` that comes back carries `worklist_items`, which the hold and the
chat relay pass on as the item a reply answers. The model can name an item
only from what it was shown, and an id that is not an open item is dropped.

WHY IT EXISTS. `submit_triage_decision` gained a `worklist_item` field, but
nothing triage read ever carried an item id, so the field could be filled only
by guessing, which its own description forbids. A page about an open
item would still have carried no id.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The model stub
holds no id of its own: it reads the id out of the user turn, from the line
that names the item whose title the alert is about, and submits that. Item 12
is written by hand as an open item of the owner's titled after the alert, so a turn
that shows it gives 12 and a turn that does not gives nothing. A stub that
names an id no open item has must come back with no item.

A page triage ties to a worklist item reaches the relay feed as concerning that item.

WHAT IT PINS. The whole page road at its public seams: `/webhook/alertmanager`
with `core.triage` behind it, the hold in `core.page_hold` and its `release`,
then `core.sent_feed.sends_after` (the read behind `GET /relay/sent`) and
`openclaw_watch.chat_relay.note`, the text the gateway's chat session reads.
The model is a stub that pages and names worklist item 36 in its submit.

WHY IT EXISTS. A page can go to the owner while triage's own reason says
"tracked on worklist item 36". If the page text leaves the item out and nothing
carries it, the owner's "done" is read as being about something else, item 36
stays open, and the next brief reads it as "Blind spot unchanged".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The model
stub names item 36, which is open and the owner's. The send the relay reads must
concern 36, and the note must name the call that records a reply to it. A
second page whose submit names no item must reach the relay concerning nothing.

A patrol question reaches the relay feed as concerning the worklist item its pass opened.

WHAT IT PINS. The `/webhook/patrol` route with `core.patrol.patrol` behind it,
the real `manage_worklist` write a pass makes, then `core.sent_feed.sends_after`
(the read behind `GET /relay/sent`) and `openclaw_watch.chat_relay.note`. The
model is a stub that files a watch item as bookkeeping, then files one
question and asks it; the send to Signal is a stub that lands.

WHY IT EXISTS. Patrol files the question it asks on the worklist so it
remembers it asked, and a reply closes that question only through
`record_answer`, which needs the item's id. When nothing carries the id to
the chat that hears the reply, `record_answer` is never called.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The id comes
from the worklist write itself, read back off `manage_worklist`'s own answer
inside the stub. An older open item the pass never touched, and the watch
item the same pass filed, are the ones the send must not concern: a reply can
answer only the question.

The watch item was proved by hand against `patrol._dispatch_tracked` keeping
every item a pass opened, whatever its kind: the send then concerns both.

Alerts of one shared scrape path in an envelope are triaged once, held as
one page, and all read delivered when it lands.

WHAT IT PINS. The `/webhook/alertmanager` route with `core.triage.triage_envelope`
behind it, and `core.page_hold.release`, across their public interfaces. The
model is a stub that counts its calls and always pages. A group page is not
dropped as old news while a sibling it speaks for still fires.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The envelope is
a small fixture: six TargetDown scrape-target alerts on
three blackbox jobs, all carrying `scrape_via=k8s-tunnel` as the rule now sets
it, plus one unrelated TargetDown on a job that carries no scrape_via.
That is two causes, so two model calls and two held pages; the leader of the
tunnel group is the lowest fingerprint, read off the fixture list with `min`.

Every rule in `.claude/soul.md` reaches the assistant's voice, and only the two
declared swaps do not.

WHAT IT PINS. `core/voice.py`'s public seam, `render()`, against the house
voice it is rendered from. A paraphrase of `.claude/soul.md` that nothing
compares drifts, and rules such as the em-dash ban go missing. `render()`
reads the file, and this is what stops a copy coming back.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From
`.claude/soul.md` itself, read here and split on its own bullet markers. The
expected set is every bullet the repository ships, minus exactly two things
this module declares it replaces and says why: the English-only rule, which
The assistant cannot carry because a teammate reads Dutch, and the clause telling the reader
to write a new term into `CONTEXT.md`, which the assistant has no tool for. Nothing in
the expectation is copied from `voice.py`; the file is the authority and the
two swaps are named constants, so a third silent edit fails.

A write nobody asked for is booked to the assistant, and naming the assistant reaches only the tools it may use alone.

WHAT IT PINS. The MCP door (`gates/mcp.py`), called over HTTP the way the
gateway calls it, with `requested_by: "the assistant"`. A worklist item the assistant opens on
its own is recorded as the assistant's: the item's owner and the door's audit row both
say "assistant". A message the assistant sends on its own at night is held by quiet hours,
because the self-actor's holds come with the name. A GitHub board write under
that name reaches `github_act`, because the assistant has full board write
access. A bible edit under that name is still refused
before dispatch: `create_video_call` stays person-only.

WHY IT EXISTS. A model that tries `requested_by: "assistant"` and is told the
registry holds nobody by that name reasons "the owner didn't ask here" and
books the item to the owner. The door had no honest answer to "nobody
asked".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the rules
as written: nobody asked, so the record names the assistant; quiet hours are defined as
holding the assistant's own initiative; the owner's decision opens the board to the assistant; the
bible is not among the tools the assistant may use alone.

A page leaves for a person with every UTC time on the local clock, with
the offset of the day that time falls on.

WHAT IT PINS. `shared.local_time.in_local_time` and the one seam that calls it,
`shared.signal.send`: a body sent with an empty subject (the assistant's own voice,
every page, pen message and teammate message) reaches the transport with its
"HH:MM UTC", "HH:MM:SS UTC", "HH:MMZ" and ISO "...Z" times rewritten as
"16:12 local (CEST)"; a body sent under a subject (a machine page)
reaches it byte for byte, and a time naming no zone is never touched.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. EU summer time
ends at 01:00 UTC on the last Sunday of October, 25 October 2026: before that
local is UTC+2 (CEST), from that moment UTC+1 (CET). So 14:12 UTC on 24
October is 16:12 CEST, 13:56 UTC on 26 October is 14:56 CET, and on the day
itself 00:30 UTC is 02:30 CEST while 01:30 UTC is 02:30 CET. Each expected
string is that sum, done by hand.

The one test for `apps/assistant`: the guards between a draft and
somebody's phone must catch the message that would be wrong, and leave the
honest one alone.

WHY THIS FILE IS THE WHOLE MODULE'S TEST. The assistant is built on OpenClaw,
and and nearly everything it does ends as one Signal message on a
person's phone. Every way this module can hurt anyone is a wrong
message: a calendar booking it never made, reported as done; a note
written to a teammate delivered to the owner; a wall of text sent as
one message; a deploy sha in place of news. The thing that WRITES
those messages is a call to Anthropic and cannot be tested here. Everything
standing between it and the phone can: the guards are pure text predicates
with no I/O, each with one stated rule you can apply by hand to a candidate
message and know the verdict before running anything.

WHAT AN INDEPENDENT ANSWER MEANS HERE. A case is a candidate message plus the
turn it was drafted in, and the expected verdict comes from the guard's rule,
never from a recorded output. "A draft claiming a write is allowed through only
if a matching write tool succeeded this turn" decides both halves of the
receipts cases without running anything: no receipt must nudge, the receipt
must pass, and one receipt cannot back a claim about two writes. "A patrol line
has one destination" decides the addressing cases the same way.

THE LAST PART ASSERTS PROPERTIES INSTEAD. The splitter's answer is checked
against a greedy word-packer written out here rather than imported, plus the
two things that hold for any correct splitter whatever the cap is set to: no
piece may exceed the cap, and the words must come back in order with none lost
and none cut in half. That is the failure worth catching, because the fix for
an over-long message must never become a truncated one.

NOT COVERED, deliberately: nothing here sends, and nothing here asks the model
anything. Whether a nudge actually changes what the model writes next, and
whether signal-cli then delivers it, are questions for a live run against a real
Signal account. This file is the deterministic half.

The gateway fragment pins the assistant's user timezone to Europe/local.

WHAT IT PINS. `workspace/gateway_config_patch.json`, the fragment step 68
applies with `openclaw config patch --stdin`. With `agents.defaults.userTimezone`
unset, upstream OpenClaw resolves the host zone, which on the ops VM is UTC, and
stamps every Signal envelope, every cron "Current time:" line and the prompt's
local date in UTC. The model then has to convert to local in its head, and
gets it wrong: an hour off on a time range, or the wrong weekday for
late-evening commits.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The key path is
read off the running gateway's schema (`openclaw config schema` on OpenClaw
2026.9.1, 2026-10-06): `agents.defaults.userTimezone`, a string, and upstream's
`docs/concepts/timezone.md` in github.com/openclaw/openclaw says that one key drives envelopes, queued system
events and the prompt's date (`envelopeTimezone` was removed upstream). The
zone is where the team works, an IANA name the gateway's Intl accepts.

A page and a pen message are remembered on the same local clock the owner
read them on.

WHAT IT PINS. The two roads that send in the assistant's own voice and then record
what they said: `core.page_hold.release` and `core.notify_flush.flush_pen`.
A page goes in through `state.hold_page`, a pen batch through
`state.enqueue_ping`; what Signal was handed is read off the stand-in for
`shared.signal.send`, and what the assistant remembers is read back through
`outbound.recent_sent`, the block the model reads as its own past messages.
Both must say "16:12 local (CEST)", and neither may still say
"14:12 UTC".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. On 16 October
2026 local is on summer time, UTC+2 (CEST), so 14:12 UTC is 16:12 CEST.
The sends happen at 12:00 UTC, 14:00 local, outside quiet hours and the
morning gate.

A patrol line, the minutes report and a security page leave on local time.

WHAT IT PINS. The `/webhook/patrol` and `/webhook/notulen` routes and
`core.security_sweep.sweep_security`, each with its model or filer stubbed and
its Signal send captured, then `core.sent_feed.sends_after`, the read the chat
relay copies into the chat. A "14:12 UTC" in the text a person gets must arrive
as local time, and the chat must remember the text that was sent.

WHY IT EXISTS. UTC times are rewritten at page_hold's release and in the pen's
own send, and these three roads send around both, so without this a person
would still read "14:12 UTC" in a patrol line or a security page.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The send moment
is pinned to 2026-10-22, inside the local summer time (UTC+2 until 25 October
2026), so 14:12 UTC is 16:12 there, read off the zone rules by hand.
"""
from __future__ import annotations

from apps.assistant.conftest import FROZEN_AT

import inspect
import os


# From a covering page triage reads off the awareness rows is one the claim gate can find.

import re


from types import SimpleNamespace


_COST_AUDIT = "99a55c63aa11bb22"


_GATE_AUDIT = "63670a81cc33dd44"


_CLAIM = "same dead textfile service already paged"


_RELEASED_ROW = re.compile(r"UnitFailed \[([^\]]+)\] -> released")


def _seed(state) -> None:
    """Cost-audit delivered on its own fingerprint, gate-full-audit never."""
    state.record_alert(
        fingerprint=_COST_AUDIT, name="UnitFailed", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )
    state.record_alert(
        fingerprint=_GATE_AUDIT, name="UnitFailed", severity="warning",
        status="firing", decision="silent", reason=_CLAIM,
        signal_sent=False, dead_letter=False,
    )


def _a_covering_page_triage_reads_off_the_awareness_rows_is_one_the_claim_gate_can_find(
    tmp_path, monkeypatch
) -> None:
    """The fingerprint copied off the delivered row covers the silence."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import awareness, brain, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    _seed(state)
    shown_fingerprints = _RELEASED_ROW.findall(awareness.render())
    assert len(shown_fingerprints) == 1
    named = shown_fingerprints[0]

    def fake_run(*, messages, **_ignored):
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "silent", "reason": _CLAIM, "signal_draft": None,
                "covered_by_fingerprint": named,
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    result = triage(
        Alert(
            fingerprint=_GATE_AUDIT, status="firing",
            labels={"alertname": "UnitFailed", "severity": "warning"},
            annotations={"summary": "a systemd unit on the ops VM failed"},
            starts_at="2026-08-31T21:40:00Z", ends_at="0001-01-01T00:00:00Z",
        )
    )
    assert result.decision == "silent"

# From a critical page leaves through quiet hours and the morning gate while a warning waits.

from apps.assistant.shared.zone import LOCAL_ZONE


from datetime import datetime


import pytest


from zoneinfo import ZoneInfo


_LOCAL_TZ = LOCAL_ZONE


_CRITICAL_FINGERPRINT = "c1a2b3c4d5e6f708"


_WARNING_FINGERPRINT = "4405b24e6462f486"


_CRITICAL = "UnitFailed: the deploy gate is red and nothing is shipping."


_WARNING = "TargetDown: signal-bridge metrics gone dark."


@pytest.fixture()
def phone(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue and a list standing in for the phone. Only the Signal
    send is replaced; every gate and every read runs against SQLite."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    # No wait for the weekday brief: these cases pin the gate's clock,
    # and the brief carrying the night is pinned on its own.
    monkeypatch.setenv("ASSISTANT_BRIEF_WAIT_MINUTES", "0")
    from apps.assistant.core import page_hold

    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return landed


def _at(hour: int, minute: int = 0) -> datetime:
    """Today at this local time."""
    return FROZEN_AT.astimezone(_LOCAL_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _page(text: str, *, key: str, severity: str, status: str = "firing") -> None:
    """One page as `gates/app` writes it: held first, then its arrival audited."""
    from apps.assistant.core import state

    state.hold_page(text, road="alertmanager", subject=text.split(":")[0],
                    severity=severity, key=key)
    _arrival(key, severity, status)


def _arrival(key: str, severity: str, status: str) -> None:
    from apps.assistant.core import state

    state.record_alert(
        fingerprint=key, name="fixture", severity=severity, status=status,
        decision="enrich" if status == "firing" else "silent",
        reason="fixture", signal_sent=False, dead_letter=False,
    )


def _release(moment: datetime) -> str | None:
    from apps.assistant.core import page_hold

    return page_hold.release(moment)


def _a_critical_leaves_inside_the_hold_and_the_warning_waits(phone, hour, minute) -> None:
    """Quiet hours (02:00) and the morning gate (07:45) both let a critical out."""
    _page(_WARNING, key=_WARNING_FINGERPRINT, severity="warning")
    _page(_CRITICAL, key=_CRITICAL_FINGERPRINT, severity="critical")

    assert _release(_at(hour, minute)) == _CRITICAL and phone == [_CRITICAL], (
        f"at {hour:02d}:{minute:02d} the critical page did not leave alone"
    )

    assert _release(_at(8, 0)) == _WARNING and phone == [_CRITICAL, _WARNING], (
        "the warning did not wait for the morning, or the critical left twice"
    )


def _a_warning_alone_is_still_held_through_the_night(phone) -> None:
    """Nothing critical waiting means the hold is exactly what it was."""
    _page(_WARNING, key=_WARNING_FINGERPRINT, severity="warning")

    assert _release(_at(2, 0)) is None and phone == []


def _a_critical_whose_alert_resolved_is_still_dropped(phone) -> None:
    """Going through the night does not skip the already-resolved check."""
    from apps.assistant.core import state

    _page(_CRITICAL, key=_CRITICAL_FINGERPRINT, severity="critical")
    _arrival(_CRITICAL_FINGERPRINT, "critical", "resolved")

    assert _release(_at(2, 0)) is None and phone == []
    assert state.pending_page_count() == 0, "the resolved critical is still waiting"

# From a failing signal send backs off instead of retrying every pass.

from datetime import timedelta, timezone


_START = datetime(2026, 10, 7, 6, 0, 20, tzinfo=timezone.utc)


@pytest.fixture()
def signal(tmp_path, monkeypatch) -> dict:
    """A fresh queue with the clocks open, a fresh outage, and a Signal whose
    answer the test sets. Every gate and every read runs against SQLite."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_QUIET_HOURS", "off")
    from apps.assistant.core import page_hold

    monkeypatch.setattr(page_hold, "_outage", page_hold._SendOutage())
    wire: dict = {"up": False, "asked": [], "landed": []}

    def send(subject: str, body: str) -> bool:
        wire["asked"].append(body)
        if wire["up"]:
            wire["landed"].append(body)
        return wire["up"]

    monkeypatch.setattr(page_hold._signal_dispatch, "send", send)
    return wire


def _not_delivered_rows() -> int:
    from apps.assistant.core import state

    return sum(
        1 for row in state.list_recent_alerts(500) if row["decision"] == "not-delivered"
    )


def _passes(start: datetime, count: int) -> None:
    from apps.assistant.core import page_hold

    for step in range(count):
        page_hold.release(start + timedelta(seconds=30 * step))


def _an_outage_costs_a_send_per_backoff_step_not_per_pass(signal) -> None:
    from apps.assistant.core import state

    state.hold_page("the night: 3 pings, all clear", road="pen", subject="the night")
    _passes(_START, 41)

    assert len(signal["asked"]) == 6, (
        f"{len(signal['asked'])} sends in 20 minutes of outage, not one per backoff step"
    )
    assert _not_delivered_rows() == 6, "each failed send writes exactly one row"


def _the_late_message_says_so_and_the_next_outage_starts_short(signal) -> None:
    from apps.assistant.core import page_hold, state

    state.hold_page("the night: 3 pings, all clear", road="pen", subject="the night")
    _passes(_START, 41)

    signal["up"] = True
    back = _START + timedelta(seconds=1830)
    assert page_hold.release(back) is not None
    assert len(signal["landed"]) == 1
    assert signal["landed"][0].startswith("Late: Signal stopped delivering at 08:00"), (
        signal["landed"][0]
    )
    assert "the night: 3 pings, all clear" in signal["landed"][0]

    signal["up"] = False
    state.hold_page("a second page", road="pen", subject="later")
    later = back + timedelta(hours=1)
    asked = len(signal["asked"])
    _passes(later, 2)
    assert len(signal["asked"]) - asked == 2, (
        "the second outage inherited the first one's long wait"
    )

# From a filed mute holds for every spelling of its subject.

_BARE = "auto-deploy: a commit was reverted on main"


_MARKED = "\U0001f534 " + _BARE


_BANNERED = "\U0001f534 [the project] " + _BARE


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """A fresh state file of this test's own; nothing leaves the box."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import state as state_module

    return state_module


def _a_card_filed_off_the_bare_spelling_mutes_the_marked_ping(state) -> None:
    """The an issue shape: filed bare, the next ping red and bannered, must_page set."""
    from apps.assistant.core import notify_flush

    state.record_filed(_BARE, 41)
    ping = {"id": 1, "subject": _BANNERED, "facts": {"must_page": "yes"}}

    live, silenced = notify_flush._split_silenced([ping])

    assert not live and [held["id"] for held in silenced] == [1], (
        "a ping on a filed subject paged because its sender wrote a marker, a "
        "banner or must_page in front of the same sentence"
    )


def _a_row_stored_with_a_marker_is_found_and_lifted_by_any_spelling(state) -> None:
    """Rows written before the key existed carry the marker; they still count."""
    from apps.assistant.core.state.conn import get_connection

    later = (FROZEN_AT + timedelta(days=30)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO filed_observations (subject, issue_number, filed_at, "
            "expires_at) VALUES (?, ?, ?, ?)",
            (_MARKED, 1, FROZEN_AT.isoformat(), later),
        )
        conn.commit()

    assert state.filed_issue_for(_BARE) == 1, "the bare lookup missed the old marked row"
    assert state.clear_filed(_BANNERED) is True, "the lift did not find the old row"
    assert state.filed_issue_for(_MARKED) is None, "the lifted mute still holds"


def _a_subject_critical_in_one_spelling_is_never_filed(state, monkeypatch) -> None:
    """Three bare days and one red day: the red day makes it unfileable."""
    from apps.assistant.core import recurring_alerts

    today = FROZEN_AT.replace(hour=6, minute=0, second=0, microsecond=0)
    rows = [
        {
            "name": state.batch_row_name(1, [_BARE]),
            "severity": "info",
            "received_at": (today - timedelta(days=days_ago)).isoformat(),
        }
        for days_ago in (1, 2, 3, 4)
    ]
    rows.append(
        {
            "name": state.batch_row_name(1, [_MARKED]),
            "severity": "critical",
            "received_at": (today - timedelta(days=5)).isoformat(),
        }
    )
    monkeypatch.setattr(state, "alerts_since", lambda _start, limit: rows)
    created: list[dict] = []
    monkeypatch.setattr(
        recurring_alerts.github_act,
        "execute",
        lambda payload, actor: created.append(payload) or "created #9999",
    )

    filed = recurring_alerts.file_recurring_observations()

    assert filed == [] and created == [], (
        "the bare spelling of a subject that paged red was filed and muted"
    )

# From a held page that is no longer news never reaches the phone.

_KEY = "4405b24e6462f486"


_PAGE = "TargetDown: signal-bridge metrics gone dark."


def _morning(minutes_after_eight: int = 0) -> datetime:
    """08:00 local today plus some minutes: past quiet hours and the
    morning gate, and ten minutes apart is past the five-minute story gap."""
    eight = FROZEN_AT.astimezone(_LOCAL_TZ).replace(hour=8, minute=0, second=0, microsecond=0)
    return eight + timedelta(minutes=minutes_after_eight)


def _page_5(text: str = _PAGE, *, status: str = "firing", key: str = _KEY) -> None:
    """One page as `gates/app` writes it: held first, then its arrival audited."""
    from apps.assistant.core import state

    state.hold_page(text, road="alertmanager" if key else "pen",
                    subject="TargetDown", severity="warning", key=key)
    if key:
        _arrival_5(status)


def _arrival_5(status: str) -> None:
    from apps.assistant.core import state

    state.record_alert(
        fingerprint=_KEY, name="TargetDown", severity="warning",
        status=status, decision="enrich" if status == "firing" else "silent",
        reason="fixture", signal_sent=False, dead_letter=False,
    )


def _release_5(minutes_after_eight: int = 0) -> str | None:
    from apps.assistant.core import page_hold

    return page_hold.release(_morning(minutes_after_eight))


def _a_page_whose_alert_resolved_before_it_left_is_dropped(phone) -> None:
    """Held, then the resolve, then the morning."""
    from apps.assistant.core import state

    _page_5()
    _arrival_5("resolved")

    assert _release_5() is None and phone == [], (
        "a page about an outage that had already ended reached the phone"
    )
    assert state.pending_page_count() == 0, "the stale page is still waiting"
    assert state.last_release_at() is None, "a dropped page moved the pacing clock"


def _a_flap_is_still_firing_and_still_pages(phone) -> None:
    """Resolved and firing again before the morning is firing at breakfast."""
    _page_5()
    _arrival_5("resolved")
    _arrival_5("firing")

    assert _release_5() is not None and len(phone) == 1


def _a_page_saying_the_thing_came_back_is_not_stale(phone) -> None:
    """Its own arrival was the resolve, so the resolve cannot make it stale."""
    _page_5("signal-bridge is publishing again.", status="resolved")

    assert _release_5() is not None and len(phone) == 1


def _one_firing_episode_pages_once_and_a_new_one_pages_again(phone) -> None:
    """The same unresolved alert, three mornings."""
    _page_5()
    assert _release_5(0) is not None, "the first page of the episode never left"

    _page_5(_PAGE + " Still dark.")
    _arrival_5("firing")
    assert _release_5(10) is None and len(phone) == 1, (
        "a second page in one unresolved firing episode reached the phone"
    )

    _arrival_5("resolved")
    _page_5(_PAGE + " Dark again.")
    assert _release_5(20) is not None and len(phone) == 2, (
        "a firing that started after a resolve was taken for the old episode"
    )


def _a_page_with_no_fingerprint_is_never_dropped(phone) -> None:
    """The pen's merged night carries no identity to ask about."""
    _page_5("the night: 24 pings, the deploy queue is red", key="")
    _arrival_5("resolved")

    assert _release_5() is not None and len(phone) == 1

# From a held page the morning brief names is not sent again and one it leaves out still is.

_ALEX = "+15550100001"


_DEGRADED = "TargetDown: signal-bridge metrics gone dark at 01:42."


_DISK = "ResourceHigh: the ops VM disk is at 88 percent."


_BRIEF = (
    "Today: standup 10:00. Held overnight: TargetDown, Fri 01:42 "
    "local, still dark."
)


@pytest.fixture()
def phone_6(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue and a list standing in for the phone. Only the Signal
    send is replaced; every gate and every read runs against SQLite."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    for name in ("ASSISTANT_QUIET_HOURS", "ASSISTANT_MORNING_GATE_UNTIL", "ASSISTANT_BRIEF_WAIT_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    from apps.assistant.core import page_hold, state

    state.reset_for_tests()
    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return landed


def _at_6(day: int, hour: int, minute: int = 0) -> datetime:
    """That October 2026 day at this local wall-clock time."""
    return datetime(2026, 10, day, hour, minute, tzinfo=_LOCAL_TZ)


def _night(day: int) -> None:
    """Two warnings held in the small hours, as triage holds them."""
    from apps.assistant.core import state

    for text, hour in ((_DEGRADED, 1), (_DISK, 3)):
        state.hold_page(
            text, road="alertmanager", subject=text.split(":")[0], severity="warning",
            now=_at_6(day, hour, 53).astimezone(timezone.utc).isoformat(),
        )


def _brief_lands(moment: datetime, text: str = _BRIEF) -> None:
    """The chat turn `message_teammate` writes once the brief is delivered."""
    from apps.assistant.core.state.conn import get_connection

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO chat_turns (sender, role, text, created_at, loop) "
            "VALUES (?, 'assistant', ?, ?, 'teammate-self')",
            (_ALEX, text, moment.astimezone(timezone.utc).isoformat()),
        )
        conn.commit()


def _the_brief_carries_what_it_names_and_the_rest_still_leaves(phone_6) -> None:
    from apps.assistant.core import state

    _night(23)
    assert _release(_at_6(23, 8, 0)) is None and phone_6 == [], (
        "on a weekday the night left at 08:00 instead of waiting for the brief"
    )

    _brief_lands(_at_6(23, 8, 4))
    _release(_at_6(23, 8, 5))

    assert phone_6 == [_DISK], f"expected only the page the brief left out, got {phone_6}"
    assert state.pending_page_count() == 0, "a page the brief carried is still waiting"


def _with_no_brief_the_night_leaves_when_the_wait_runs_out(phone_6) -> None:
    _night(23)

    assert _release(_at_6(23, 8, 15)) is None and phone_6 == []
    _release(_at_6(23, 8, 30))

    assert len(phone_6) == 1 and _DEGRADED in phone_6[0] and _DISK in phone_6[0], (
        f"a weekday with no brief lost part of the night: {phone_6}"
    )


def _a_saturday_night_leaves_at_eight(phone_6) -> None:
    _night(24)

    _release(_at_6(24, 8, 0))

    assert len(phone_6) == 1 and _DEGRADED in phone_6[0] and _DISK in phone_6[0], (
        f"a Saturday waited for a brief that never runs: {phone_6}"
    )


_PINGS = [
    {"subject": "auto-deploy: gate red on main"},
    {"subject": "batch done [nightly]"},
]


_PEN_PAGE = "Gate red at 02:10, batch done at 22:03."


def _the_pens_night_page_is_carried_only_when_the_brief_names_each_subject(
    phone_6, brief, sent, monkeypatch
) -> None:
    """The pen queues its page under the batch's own subjects: a brief naming
    one of two does not carry it, a brief naming both does."""
    from apps.assistant.core import notify_flush
    from apps.assistant.core.state import page_hold as held_pages

    queued_at = _at_6(23, 7, 31).astimezone(timezone.utc).isoformat()
    monkeypatch.setattr(held_pages, "utcnow_iso", lambda: queued_at)
    notify_flush._hold_for_the_brief(_PEN_PAGE, _PINGS)
    _brief_lands(_at_6(23, 8, 3), brief)
    _release(_at_6(23, 8, 5))

    assert phone_6 == sent, f"brief {brief!r} left the phone with {phone_6}"

# From a lifted or lapsed mute is never refiled from the occurrences it already decided.

_SUBJECT = "systemd unit failed: harness-webhook-self-heal.service"


@pytest.fixture()
def filer(tmp_path, monkeypatch):
    """A fresh state file, hand-written audit rows, and GitHub as a counter.

    Returns (rows, created): append to `rows` to add arrivals; `created` lists
    every issue the filer asked GitHub for.
    """
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import recurring_alerts, state

    rows: list[dict] = []
    created: list[dict] = []
    monkeypatch.setattr(state, "alerts_since", lambda _start, limit: list(rows))

    def create(payload: dict, actor: str) -> str:
        created.append(payload)
        return f"created https://github.com/o/r/issues/{len(created)}"

    monkeypatch.setattr(recurring_alerts.github_act, "execute", create)
    return rows, created


def _arrivals_on(rows: list[dict], days_from_now: list[float]) -> None:
    from apps.assistant.core import state

    now = FROZEN_AT
    for offset in days_from_now:
        rows.append({
            "name": state.batch_row_name(1, [_SUBJECT]),
            "severity": "warning",
            "received_at": (now + timedelta(days=offset)).isoformat(),
        })


def _a_lifted_mute_is_not_refiled_from_the_rows_that_filed_it(filer) -> None:
    from apps.assistant.core import recurring_alerts, state

    rows, created = filer
    _arrivals_on(rows, [-4, -3, -2])
    assert [one.number for one in recurring_alerts.file_recurring_observations()] == [1]

    assert state.clear_filed(_SUBJECT) is True
    assert recurring_alerts.file_recurring_observations() == []
    assert len(created) == 1, "the lifted subject was refiled off its old rows"

    _arrivals_on(rows, [0.5, 1.5, 2.5])
    assert [one.number for one in recurring_alerts.file_recurring_observations()] == [2], (
        "three new days after the lift did not file the subject again"
    )


def _a_lapsed_mute_is_not_refiled_from_the_rows_before_it_lapsed(filer) -> None:
    from apps.assistant.core import recurring_alerts, state

    rows, created = filer
    _arrivals_on(rows, [-4, -3, -2])
    state.record_filed(_SUBJECT, 3, ttl_days=0)

    assert recurring_alerts.file_recurring_observations() == []
    assert created == [], "a lapsed card was refiled off the rows before it lapsed"

# From a page never ends on the lead in of a fix step whose command was stripped.

import json


from apps.assistant.core.signal_text import strip_markdown


_STALL_DRAFT = (
    "harness-github-mail-janitor.timer is stalled. It has no next run scheduled.\n"
    "\n"
    "To un-stall it:\n"
    "ssh deploy@203.0.113.10 'sudo systemctl restart harness-github-mail-janitor.timer'\n"
    "\n"
    "Then confirm the unit has OnActiveSec= so the stall cannot recur."
)


_GAP_DRAFT = (
    "OOM killer fired on the VM around 10:50 UTC. Memory has recovered.\n"
    "\n"
    "sudo dmesg -T | grep -i 'killed process'\n"
    "\n"
    "Cluster pods all look fine."
)


_READ_ONLY_DRAFT = (
    "Repo index build has been failing since 09:21 UTC today.\n"
    "\n"
    "No Loki trace, need the VM log:\n"
    "grep '[graph]' /var/log/harness/auto-deploy.log | tail -20"
)


_CHAT_ANSWER = (
    "Three things landed this morning:\n"
    "the deploy at 09:29\n"
    "the Caddy path rewrite\n"
    "\n"
    "Also, the index caught up at 10:02."
)


def _a_stripped_command_takes_its_lead_in_and_its_next_step_with_it() -> None:
    """The stall page keeps what is wrong and loses the whole fix step."""
    assert strip_markdown(_STALL_DRAFT) == (
        "harness-github-mail-janitor.timer is stalled. It has no next run scheduled."
    )


def _a_dropped_line_leaves_one_blank_line_not_two() -> None:
    """The blank lines either side of a dropped command do not both survive."""
    assert strip_markdown(_GAP_DRAFT) == (
        "OOM killer fired on the VM around 10:50 UTC. Memory has recovered.\n"
        "\n"
        "Cluster pods all look fine."
    )


def _a_read_only_command_line_goes_with_its_lead_in() -> None:
    """grep and tail at the start of a line are commands too."""
    assert strip_markdown(_READ_ONLY_DRAFT) == (
        "Repo index build has been failing since 09:21 UTC today."
    )


def _a_message_with_nothing_stripped_is_left_alone() -> None:
    """A chat answer with a colon lead-in and an "Also" line keeps both, because
    nothing next to them was a command."""
    assert strip_markdown(_CHAT_ANSWER) == _CHAT_ANSWER


@pytest.fixture()
def shown_to_model(tmp_path, monkeypatch) -> list[str]:
    """Run `triage` with the model replaced by a stub that records the alert it
    was shown and submits the stall draft. Nothing leaves the box."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, tools

    seen: list[str] = []
    submit = SimpleNamespace(
        type="tool_use",
        id="submit-1",
        name=tools.SUBMIT_NAME,
        input={"decision": "enrich", "reason": "stalled timer", "signal_draft": _STALL_DRAFT},
    )

    def fake_run(*, messages, **_ignored):
        seen.append(messages[0]["content"])
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    return seen


def _triage_never_shows_the_model_the_first_action_command(shown_to_model) -> None:
    """The ssh command in `first_action` never reaches the model, the rest of the
    annotations do, and the page that comes back has no dangling lead-in."""
    from apps.assistant.core.triage import Alert, triage

    alert = Alert(
        fingerprint="0ecb7af15224b2ab",
        status="firing",
        labels={"alertname": "VMTimerStalled", "severity": "warning"},
        annotations={
            "summary": "harness-github-mail-janitor.timer has no next elapse",
            "first_action": "ssh deploy@203.0.113.10 'sudo systemctl restart x.timer'",
        },
        starts_at="2026-09-28T14:20:00Z",
        ends_at="0001-01-01T00:00:00Z",
    )
    result = triage(alert)
    shown, _rest = json.JSONDecoder().raw_decode(shown_to_model[0])
    assert "first_action" not in shown["annotations"]
    assert shown["annotations"]["summary"] == alert.annotations["summary"]
    assert "ssh" not in shown_to_model[0]
    assert result.signal_draft is not None
    assert not result.signal_draft.rstrip().endswith(":")
    assert "Then confirm" not in result.signal_draft

# From a page never hands the reader a unit nobody read or a repair nothing backs.

from pathlib import Path


#: The alert as Prometheus renders it: a summary, a description and the
#: first_action pointer to its evidence, which is for the model and not for
#: the reader.
_ANNOTATIONS = {
    "summary": "The nightly backup index has not been refreshed for 30m",
    "first_action": (
        "db_query `SELECT created_at, detail FROM ops_activity WHERE "
        "action_type='backup_index' ORDER BY id DESC LIMIT 5`: detail.outcome "
        "names which step failed"
    ),
    "description": (
        "Every cycle builds the backup index and copies it into place, and for "
        "30 minutes the cycles that tried have failed at one of the two."
    ),
}


_UNIT_PAGE = (
    "The nightly backup index is 6h behind. Needs a look at the server-side "
    "backup-index-push service log."
)


_REMEDY_PAGE = "All 8 tls-watchdog targets dark since 16:21. Need the watchdog restarted."


def _repo_index_annotations() -> dict[str, str]:
    return dict(_ANNOTATIONS)


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, tools
    from apps.assistant.core.triage import Alert, triage

    shown: list = []
    script = {"draft": _UNIT_PAGE}

    def fake_run(*, messages, **_ignored):
        shown.append(messages[-1]["content"])
        submit = SimpleNamespace(
            type="tool_use", id=f"submit-{len(shown)}", name=tools.SUBMIT_NAME,
            input={"decision": "enrich", "reason": "lagging", "signal_draft": script["draft"]},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run(annotations: dict[str, str]):
        return triage(
            Alert(
                fingerprint="8585a3cfcf246c8b", status="firing",
                labels={"alertname": "TargetDown", "severity": "warning",
                        "component": "backup-index"},
                annotations=annotations,
                starts_at="2026-03-10T09:58:00Z", ends_at="0001-01-01T00:00:00Z",
            )
        )

    return SimpleNamespace(run=run, shown=shown, script=script)


def _the_alerts_pointer_to_its_evidence_reaches_the_model(pod) -> None:
    pod.run(_repo_index_annotations())
    assert "where_to_look_not_for_the_reader" in pod.shown[0]
    assert "ops_activity" in pod.shown[0]


def _a_unit_nothing_read_is_asked_about_then_left_out(pod) -> None:
    result = pod.run(_repo_index_annotations())
    assert len(pod.shown) == 2
    assert "backup-index-push" in str(pod.shown[1])
    assert "backup-index-push" not in (result.signal_draft or "")


def _a_repair_nothing_backs_is_asked_about_then_left_out(pod) -> None:
    pod.script["draft"] = _REMEDY_PAGE
    result = pod.run({"summary": "Prometheus target tls-watchdog down 15m"})
    assert len(pod.shown) == 2
    assert "restarted" not in (result.signal_draft or "")


def _the_pods_voice_no_longer_teaches_giving_up_on_the_journal() -> None:
    from apps.assistant.core import voice

    assert "can't read it from here" not in " ".join(voice.render().split())


def _hyphenated_english_before_service_is_not_a_unit(sentence) -> None:
    from apps.assistant.core import claims

    assert claims.unread_units(sentence, "") == []


def _a_true_page_keeps_its_symptom_line_about_a_hyphenated_service(pod) -> None:
    pod.script["draft"] = "Webapp is down; the health-check service answers 502."
    result = pod.run({"summary": "Webapp probe failing 10m"})
    assert len(pod.shown) == 1
    assert result.signal_draft == pod.script["draft"]

# From a page that dropped never reads as sent in the current picture.

_DROPPED = "ce1ac10765267c1e"


_WAITING = "9c620cfb66dd863e"


_NEVER_HELD = "5150d716aa00bb11"


_REASON = "this firing was already paged at 2000-01-01T12:00:00"


@pytest.fixture()
def picture(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import awareness, state

    for fingerprint in (_DROPPED, _WAITING, _NEVER_HELD):
        if fingerprint != _NEVER_HELD:
            held = state.hold_page(
                "TargetDown: tls-watchdog dark.", road="alertmanager",
                subject="TargetDown", severity="warning", key=fingerprint,
            )
            if fingerprint == _DROPPED:
                state.mark_dropped([held], reason=_REASON)
        state.record_alert(
            fingerprint=fingerprint, name="TargetDown", severity="warning",
            status="firing", decision="enrich", reason="fixture",
            signal_sent=False, dead_letter=False,
        )
    return awareness.render()


def _line(picture: str, fingerprint: str) -> str:
    return next(line for line in picture.splitlines() if f"[{fingerprint}]" in line)


def _a_dropped_page_says_it_was_never_sent_and_why(picture) -> None:
    line = _line(picture, _DROPPED)
    assert "dropped, never sent" in line
    assert _REASON in line


def _a_waiting_page_says_it_has_not_gone_yet(picture) -> None:
    assert "held, not sent yet" in _line(picture, _WAITING)


def _a_page_that_was_never_queued_says_not_delivered(picture) -> None:
    assert _line(picture, _NEVER_HELD).endswith("(not delivered)")

# From a pen silence names the card or suppression that held it.

_REVERT = "\U0001f534 auto-deploy: a commit was reverted on main"


_PROBE = "systemd unit failed: harness-auth-journey-probe.service"


# 14:00 local: outside quiet hours and the morning gate.
_AFTERNOON = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def state_11(tmp_path, monkeypatch):
    """A fresh state file of this test's own; nothing leaves the box."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    from apps.assistant.core import state as state_module

    return state_module


def _silenced_reason(state_11) -> str:
    rows = [
        row for row in state_11.list_recent_alerts(50) if row["decision"] == "batch-silenced"
    ]
    assert len(rows) == 1, f"expected one batch-silenced row, got {len(rows)}"
    return str(rows[0]["reason"])


def _a_filed_silence_names_its_cards(state_11) -> None:
    from apps.assistant.core import notify_flush

    state_11.record_filed("auto-deploy: a commit was reverted on main", 41)
    state_11.record_filed(_PROBE, 42)
    state_11.enqueue_ping(_REVERT, "eject reverted abc123", "notify")
    state_11.enqueue_ping(_PROBE, "journey broken at mfa_challenge", "notify")

    assert notify_flush.flush_pen(_AFTERNOON) is None
    reason = _silenced_reason(state_11)
    assert "#41" in reason and "#42" in reason, (
        f"the silenced row does not say which card held it: {reason!r}"
    )


def _a_suppressed_silence_names_the_suppression(state_11) -> None:
    from apps.assistant.core import notify_flush

    state_11.add_suppression(_PROBE, "Alex: single probe blips, AuthJourneyBroken covers it")
    state_11.enqueue_ping(_PROBE, "login answered http 502", "notify")

    assert notify_flush.flush_pen(_AFTERNOON) is None
    reason = _silenced_reason(state_11)
    assert "single probe blips" in reason, (
        f"the silenced row does not say which suppression held it: {reason!r}"
    )

# From a ping a closed card still mutes is reported in the brief and the mute is not lifted.

import subprocess


_SINCE = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


_REVERT_12 = "auto-deploy: a commit was reverted on main"


_GITHUB_SAYS = {
    "data": {
        "repository": {
            "i41": {"state": "CLOSED"},
            "i42": {"state": "CLOSED"},
            "i43": {"state": "OPEN"},
        }
    }
}


@pytest.fixture()
def cards(tmp_path, monkeypatch) -> list[list[str]]:
    """The three cards, their pings, and a stand-in for `gh` that records
    every call made to it."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import state
    from apps.assistant.core.state.conn import get_connection
    from apps.assistant.core.tools.gh import issue_states

    state.reset_for_tests()
    issue_states._cache.clear()
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO filed_observations (subject, issue_number, filed_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            [
                (_REVERT_12, 41, "2026-09-07T09:00:00+00:00", "2099-12-06T09:00:00+00:00"),
                ("nightly unit failed: harness-backup", 42, "2026-09-15T09:00:00+00:00",
                 "2099-12-14T09:00:00+00:00"),
                ("dependency scan found vulnerabilities", 43, "2026-10-01T09:00:00+00:00",
                 "2099-12-30T09:00:00+00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO notify_pen (subject, body, source, received_at, flushed_at) "
            "VALUES (?, 'body', 'notify', ?, ?)",
            [
                (_REVERT_12, "2026-10-15T22:40:00+00:00", "2026-10-15T22:41:00+00:00"),
                (f"\U0001f534 {_REVERT_12}", "2026-10-16T04:12:00+00:00", "2026-10-16T04:13:00+00:00"),
                ("dependency scan found vulnerabilities", "2026-10-16T03:00:00+00:00",
                 "2026-10-16T03:01:00+00:00"),
                (_REVERT_12, "2026-10-14T22:00:00+00:00", "2026-10-14T22:01:00+00:00"),
            ],
        )
        conn.commit()

    calls: list[list[str]] = []

    def fake_gh(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(_GITHUB_SAYS), "")

    monkeypatch.setattr(issue_states.subprocess, "run", fake_gh)
    return calls


def _each_closed_card_is_one_line_and_the_open_one_is_not_named(cards) -> None:
    from apps.assistant.core import closed_card_mutes

    lines = closed_card_mutes.report(_SINCE)

    assert lines == [
        "#42 is closed and still mutes 'nightly unit failed: harness-backup' until "
        "2099-12-14; nothing silenced since the last brief.",
        f"#41 is closed and still mutes '{_REVERT_12}' until 2099-12-06; it silenced "
        "2 ping(s) since the last brief, the last at Fri 06:12 local.",
    ], lines


def _github_is_asked_once_and_the_mute_still_stands(cards) -> None:
    from apps.assistant.core import closed_card_mutes, state

    closed_card_mutes.report(_SINCE)
    closed_card_mutes.report(_SINCE)

    assert len(cards) == 1, f"expected one cached GitHub call, got {len(cards)}"
    assert state.filed_issue_for(_REVERT_12) == 41, "reporting the card lifted its mute"


def _the_brief_reads_it_through_my_actions(cards, monkeypatch) -> None:
    from apps.assistant.core.tools.meta import my_actions

    monkeypatch.setattr(my_actions, "_since_the_last_brief", lambda: _SINCE)

    answer = my_actions.execute({})

    assert "Muted by a card that is closed" in answer and "#41 is closed" in answer, answer

# From a resolve of a paged alert sends an all clear even inside the dedup window.

_FINGERPRINT = "a1b2c3d4e5f60718"


_NOON = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pod_13(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    calls: list[int] = []

    def fake_run(**_ignored):
        calls.append(1)
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={"decision": "enrich", "reason": "down", "signal_draft": "Webapp is down."},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    landed: list[str] = []
    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(
        page_hold._signal_dispatch, "send", lambda subject, body: landed.append(body) or True
    )

    def alert(status: str):
        return Alert(
            fingerprint=_FINGERPRINT, status=status,
            labels={"alertname": "ServiceDown", "severity": "warning"},
            annotations={"summary": "app.example.org probe failing"},
            starts_at="2026-10-18T13:53:00Z", ends_at="2026-10-18T14:02:25Z",
        )

    def arrival(status: str, *, delivered: bool = False) -> None:
        state.record_alert(
            fingerprint=_FINGERPRINT, name="ServiceDown", severity="warning",
            status=status, decision="enrich", reason="fixture",
            signal_sent=delivered, dead_letter=False,
        )

    def hold(text: str) -> None:
        state.hold_page(text, road="alertmanager", subject="ServiceDown",
                        severity="warning", key=_FINGERPRINT)

    return SimpleNamespace(
        triage=lambda status: triage(alert(status)), arrival=arrival, hold=hold,
        release=page_hold.release, calls=calls, landed=landed,
    )


def _a_resolve_inside_the_dedup_window_of_a_delivered_page_is_an_all_clear(pod_13) -> None:
    pod_13.triage("firing")
    pod_13.arrival("firing", delivered=True)
    result = pod_13.triage("resolved")
    assert result.decision != "silent"
    assert result.reason.startswith("all-clear")
    assert result.signal_draft and result.signal_draft.startswith("Stopped firing")
    assert len(pod_13.calls) == 1


def _a_resolve_of_a_firing_nobody_heard_about_stays_silent(pod_13) -> None:
    pod_13.arrival("firing")
    result = pod_13.triage("resolved")
    assert result.decision == "silent"
    assert not pod_13.calls


def _the_all_clear_never_reads_as_the_next_episodes_page(pod_13) -> None:
    pod_13.hold("Webapp is down.")
    pod_13.arrival("firing")
    pod_13.release(now=_NOON)
    all_clear = pod_13.triage("resolved")
    pod_13.hold(all_clear.signal_draft)
    pod_13.arrival("resolved")
    pod_13.release(now=_NOON.replace(minute=20))
    pod_13.hold("Webapp is down again.")
    pod_13.arrival("firing")
    pod_13.release(now=_NOON.replace(minute=40))
    assert pod_13.landed[1].startswith("Stopped firing")
    assert pod_13.landed[-1] == "Webapp is down again."

# From a second secret scan finding is a new commit not a repeat.

from apps.assistant.core import page_render, ping_facts


SUBJECT = "\U0001f6a8 [the project] auto-deploy: secret scan found a possible committed secret"


BODY = (
    "SHA: {sha}\n"
    "gitleaks reports findings in the new commits. Findings are redacted\n"
    "here; full pointers in the scan log on the VM.\n"
    "If real: rotate the secret FIRST, then scrub the history.\n\n"
    "gitleaks tail (redacted):\n"
    "\x1b[90m11:30AM\x1b[0m \x1b[33mWRN\x1b[0m \x1b[1mleaks found: 1\x1b[0m"
)


FIRST = {
    "id": 11,
    "subject": SUBJECT,
    "body": BODY.format(sha="1111111111aa1111111111aa1111111111aa1111"),
    "received_at": "2030-01-15T09:00:00+00:00",
    "facts": {"exit_code": "1", "blocks_deploy": "no"},
}


SECOND = {
    "id": 12,
    "subject": SUBJECT,
    "body": BODY.format(sha="2222222222bb2222222222bb2222222222bb2222"),
    "received_at": "2030-01-15T11:30:00+00:00",
    "facts": {"exit_code": "1", "blocks_deploy": "no"},
}


GATE_RED = {
    "id": 13,
    "subject": "\U0001f534 [the project] auto-deploy: verification gate RED",
    "body": "SHA: 0123456789abcdef0123456789abcdef01234567\nThe gate refused it.",
    "received_at": "2030-01-15T11:30:00+00:00",
}


def _seen_twice(_subject: str) -> dict:
    return {"seen_count": 2, "last_delivered_at": "2030-01-15T09:00:20+00:00"}


def _pages(row: dict) -> list[str]:
    """Every page the pen could send with `row` as the whole batch."""
    batch = ping_facts.bundle([row], history_of=_seen_twice)
    return [
        page_render.render(selection, batch, language=language)
        for language in ("en", "nl")
        for selection in page_render.every_selection(batch)
        if selection.verdict == "page"
    ]


def _a_second_finding_is_not_called_a_repeat() -> None:
    (fact,) = ping_facts.bundle([SECOND], history_of=_seen_twice)
    assert not page_render.licenses_aspect(fact, "escalation")
    for page in _pages(SECOND):
        assert "time on this subject" not in page, page
        assert "keer over dit onderwerp" not in page, page


def _each_finding_names_its_own_commit() -> None:
    for row, commit in ((FIRST, "1111111"), (SECOND, "2222222")):
        pages = _pages(row)
        assert pages
        for page in pages:
            assert f"Commit {commit}." in page, page


def _a_gate_red_repeat_still_escalates_and_prints_no_sha() -> None:
    (fact,) = ping_facts.bundle([GATE_RED], history_of=_seen_twice)
    assert page_render.licenses_aspect(fact, "escalation")
    for page in _pages(GATE_RED):
        assert not re.search(r"\b[0-9a-f]{7,40}\b", page), page

# From a send from outside the recipients session is in the relay feed once with the number that keys their session.

from apps.assistant.core import outbound, sent_feed, state as state_15


_BRIEF_15 = "Did Jordan give the caterer's price per head yesterday? Put the number on issue 47."


_PAGE_15 = "The nightly backup did not run; the disk is at 93%."


_ASKED = "Sam asked me to tell you the Monday briefing moves to 10:00."


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """the owner in the registry, and three sends written the way their roads write them."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    state_15.reset_for_tests()
    state_15.append_chat_turn(_ALEX, "assistant", _BRIEF_15, loop="teammate-self")
    outbound.remember_sent("", _PAGE_15)
    state_15.append_chat_turn(_ALEX, "assistant", _ASKED, loop="teammate-asked")
    state_15.append_chat_turn(_ALEX, "user", "Yes")


def _every_send_from_outside_the_recipients_session_is_in_the_feed_with_their_number(
    sent: None,
) -> None:
    """The brief, the page and the asked-for message come back in order, named, with the owner's number."""
    feed = sent_feed.sends_after(0)
    texts = [send["text"] for send in feed.sends]
    assert texts == [_BRIEF_15, _PAGE_15, _ASKED], (
        f"the relay feed held {texts!r}; it must hold the brief, the page and the "
        "message Sam asked for, in that order"
    )
    assert {send["recipient"] for send in feed.sends} == {"Alex"}, "a send is not named by its recipient"
    assert {send["address"] for send in feed.sends} == {_ALEX}, "a send does not carry the number its session is keyed by"


def _nothing_comes_back_past_the_last_send_returned(sent: None) -> None:
    """A relay that advanced its cursor to the last id never sees that send again."""
    first = sent_feed.sends_after(0)
    again = sent_feed.sends_after(int(first.sends[-1]["id"]))
    assert again.sends == [], "a send already relayed came back, so it would be injected twice"
    assert again.newest_id >= first.sends[-1]["id"]

# From a silence that names its cover only in prose is asked once for it before it becomes a raw page.

_COVER = "a1b2c3d4e5f60718"


_SILENCED = "0f1e2d3c4b5a6978"


_PROSE = (
    "The tls-watchdog targets-down event was already paged to Alex earlier "
    "today; covered by the earlier page."
)


_NOON_16 = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pod_16(tmp_path, monkeypatch):
    """A fresh table and a model stub whose answers the test scripts."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    turns: list[str] = []
    script: dict = {"reason": _PROSE, "cover_if_shown": None}

    def fake_run(*, messages, **_ignored):
        last = messages[-1]["content"]
        shown = last if isinstance(last, str) else last[0]["content"]
        turns.append(shown)
        cover = script["cover_if_shown"]
        named = cover if cover and len(turns) > 1 and cover in shown else None
        answer = {
            "decision": "silent", "reason": script["reason"], "signal_draft": None,
            "covered_by_fingerprint": script.get("cover_first") or named,
        }
        if len(turns) > 1 and script.get("page_on_retry"):
            answer = {"decision": "enrich", "reason": "paging instead",
                      "signal_draft": script["page_on_retry"]}
        submit = SimpleNamespace(
            type="tool_use", id=f"submit-{len(turns)}", name=tools.SUBMIT_NAME,
            input=answer,
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda **_ignored: True)

    def run():
        return triage(
            Alert(
                fingerprint=_SILENCED, status="firing",
                labels={"alertname": "TargetDown", "severity": "warning"},
                annotations={"summary": "Prometheus target tls-watchdog down 15m"},
                starts_at="2026-01-01T00:00:00Z", ends_at="0001-01-01T00:00:00Z",
            )
        )

    for _ in range(2):
        state.record_alert(
            fingerprint=_SILENCED, name="TargetDown", severity="warning",
            status="firing", decision="silent", reason="fixture",
            signal_sent=False, dead_letter=False,
        )
    return SimpleNamespace(
        run=run, turns=turns, script=script, state=state, page_hold=page_hold
    )


def _deliver_cover(state) -> None:
    state.record_alert(
        fingerprint=_COVER, name="TargetDown", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )


def _a_cover_described_in_prose_is_asked_for_and_then_stands(pod_16) -> None:
    _deliver_cover(pod_16.state)
    pod_16.script["cover_if_shown"] = _COVER
    result = pod_16.run()
    assert len(pod_16.turns) == 2
    assert result.decision == "silent"
    assert f"covered by the page on {_COVER}" in result.reason


def _with_nothing_delivered_or_queued_it_pages_without_asking(pod_16) -> None:
    result = pod_16.run()
    assert result.decision == "page-raw"
    assert len(pod_16.turns) == 1


def _a_silence_saying_the_condition_resolved_is_not_a_page_claim(pod_16) -> None:
    pod_16.script["reason"] = "already silenced; the condition has resolved (source_up=1)"
    result = pod_16.run()
    assert result.decision == "silent"
    assert len(pod_16.turns) == 1


def _a_queued_cover_takes_the_silenced_fingerprint_along_when_it_leaves(pod_16) -> None:
    from apps.assistant.core.state.alerts import last_delivered_at

    pod_16.state.hold_page(
        "tls-watchdog targets dark.", road="alertmanager",
        subject="TargetDown", severity="warning", key=_COVER,
    )
    pod_16.script["reason"] = f"covered by the queued page on {_COVER}"
    pod_16.script["cover_first"] = _COVER
    result = pod_16.run()
    assert result.decision == "silent"
    assert "queued page" in result.reason
    pod_16.page_hold.release(now=_NOON_16)
    assert last_delivered_at(_SILENCED)


def _a_raw_page_does_not_stop_the_checked_page_written_after_it(pod_16) -> None:
    landed: list[str] = []
    pod_16.page_hold._signal_dispatch.send = lambda subject, body: landed.append(body) or True
    for text, minute in (("[RAW] targets dark. I am passing this on unchecked.", 0),
                         ("Prometheus cannot reach the tunnel; the apps are up.", 20)):
        pod_16.state.hold_page(
            text, road="alertmanager", subject="TargetDown",
            severity="warning", key=_COVER,
        )
        pod_16.state.record_alert(
            fingerprint=_COVER, name="TargetDown", severity="warning",
            status="firing", decision="enrich", reason="fixture",
            signal_sent=False, dead_letter=False,
        )
        pod_16.page_hold.release(now=_NOON_16.replace(minute=minute))
    assert landed[-1].startswith("Prometheus cannot reach the tunnel")


def _a_resend_whose_own_page_is_queued_stays_silent_and_keeps_that_page(pod_16) -> None:
    pod_16.state.hold_page(
        "Prometheus cannot reach the tunnel; the apps are up.", road="alertmanager",
        subject="TargetDown", severity="warning", key=_SILENCED,
    )
    pod_16.script["reason"] = "Already queued for the morning; same firing."
    result = pod_16.run()
    assert result.decision == "silent"
    assert "own page queued" in result.reason
    held = pod_16.state.pending_page_for_key(_SILENCED)
    assert held["text"].startswith("Prometheus cannot reach the tunnel")


def _a_page_written_in_answer_to_the_cover_question_passes_the_draft_checks(pod_16) -> None:
    _deliver_cover(pod_16.state)
    pod_16.script["page_on_retry"] = (
        "Prometheus target tls-watchdog is down. Need the watchdog restarted."
    )
    result = pod_16.run()
    assert result.decision == "enrich"
    assert "tls-watchdog is down" in result.signal_draft
    assert "restarted" not in result.signal_draft

# From a standing fault paged long ago is paged again when triage drafts a new page.

_KEY_17 = "9c620cfb66dd863e"


_PAGE_17 = "Alert delivery drill still overdue."


@pytest.fixture()
def phone_17(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue with the clocks open and a list standing in for the
    phone. Only the Signal send is replaced."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_QUIET_HOURS", "off")
    from apps.assistant.core import page_hold

    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return landed


def _page_17(text: str) -> None:
    """One triage draft as `gates/app` writes it: held, then its arrival."""
    from apps.assistant.core import state

    state.hold_page(text, road="alertmanager", subject="TargetDown",
                    severity="warning", key=_KEY_17)
    state.record_alert(
        fingerprint=_KEY_17, name="TargetDown", severity="warning",
        status="firing", decision="enrich", reason="fixture",
        signal_sent=False, dead_letter=False,
    )


def _release_17(hours_later: float) -> str | None:
    from apps.assistant.core import page_hold

    return page_hold.release(FROZEN_AT + timedelta(hours=hours_later))


def _window_the_model_is_told() -> float:
    """The hours the triage prompt says a still-firing page stays dropped."""
    from apps.assistant.core import triage

    told = re.search(
        r"already paged in\s+the last (\d+) hours is dropped", triage._SYSTEM_PROMPT
    )
    assert told, "the triage prompt no longer states the re-page window"
    return float(told.group(1))


def _a_repage_inside_the_window_folds_and_one_after_it_goes(phone_17) -> None:
    """Delivered, re-drafted inside the window (dropped), then after it (sent)."""
    window = _window_the_model_is_told()
    _page_17(_PAGE_17)
    assert _release_17(0) is not None and len(phone_17) == 1, "the first page never left"

    _page_17(_PAGE_17 + " Re-sent by Alertmanager.")
    assert _release_17(window - 1) is None and len(phone_17) == 1, (
        "a re-send inside the window the model is told reached the phone again"
    )

    _page_17(_PAGE_17 + " 57 days now, limit 40.")
    assert _release_17(window + 1) is not None and len(phone_17) == 2, (
        "a fault still firing past the window the model is told was never paged again"
    )

# From a triage page never cites an issue or a past incident its own reads did not back.

_EVENTS = (
    "18:03 Normal NodeNotSchedulable node/batch-gpu-old drained\n"
    "18:14 Normal NodeReady node/batch-gpu-new status is now: NodeReady\n"
)


_ISSUE_PAGE = (
    "Notulen job for the weekly sync failed: DeadlineExceeded. "
    "Same GPU driver-upgrade timing issue as last month (issue 42)."
)


_ANALOGY_PAGE = (
    "Notulen job for the weekly sync stuck 30+ min waiting for a GPU. "
    "Same pattern as the earlier incidents."
)


@pytest.fixture()
def pod_18(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, tools
    from apps.assistant.core.triage import Alert, triage

    world = {"reading": _EVENTS, "draft": _ISSUE_PAGE}
    shown: list = []
    monkeypatch.setattr(tools, "execute", lambda name, tool_input: world["reading"])

    def fake_run(*, messages, dispatch, **_ignored):
        shown.append(messages[-1]["content"])
        if len(shown) == 1:
            dispatch("kubectl_events", {"namespace": "notulen"})
        submit = SimpleNamespace(
            type="tool_use", id=f"submit-{len(shown)}", name=tools.SUBMIT_NAME,
            input={"decision": "enrich", "reason": "job failed", "signal_draft": world["draft"]},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run():
        return triage(
            Alert(
                fingerprint="5d1e0c7f2a9b3e41", status="firing",
                labels={"alertname": "PipelineBroken", "severity": "warning"},
                annotations={"summary": "notulen GPU job failed: DeadlineExceeded"},
                starts_at="2026-10-19T18:25:00Z", ends_at="0001-01-01T00:00:00Z",
            )
        )

    return SimpleNamespace(run=run, world=world, shown=shown)


def _a_spelled_out_issue_is_a_citation() -> None:
    from apps.assistant.core import claims

    assert claims.unread_issue_numbers("Same timing issue (issue 42).", set()) == [42]


def _an_issue_no_reading_carried_is_asked_about_then_left_out(pod_18) -> None:
    result = pod_18.run()
    assert "42" in str(pod_18.shown[1])
    assert "42" not in (result.signal_draft or "")
    assert "DeadlineExceeded" in (result.signal_draft or "")


def _an_issue_a_reading_carried_stays(pod_18) -> None:
    pod_18.world["reading"] = "title:\tGPU driver upgrade timing\nnumber:\t42\n" + _EVENTS
    result = pod_18.run()
    assert "issue 42" in (result.signal_draft or "")


def _a_diagnosis_by_analogy_to_a_past_incident_is_left_out(pod_18) -> None:
    pod_18.world["draft"] = _ANALOGY_PAGE
    result = pod_18.run()
    assert "Same pattern" not in (result.signal_draft or "")
    assert "stuck 30+ min" in (result.signal_draft or "")

# From a triage pass stores what it read beside what it said and a critical silence on an unread stamp pages.

_FINGERPRINT_19 = "f3fe41d09b35fe4b"


_REASON_19 = "Alex fixed it in commit 6f6f6f6f at 13:55 UTC, 48s after the alert fired."


@pytest.fixture()
def pod_19(tmp_path, monkeypatch):
    """A fresh table, one tool that returns `reading`, and a model that reads
    once and then silences with `_REASON`."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    world = {"reading": "HTTP/2 200"}
    monkeypatch.setattr(tools, "execute", lambda name, tool_input: world["reading"])

    def fake_run(*, dispatch, **_ignored):
        dispatch("run_shell", {"command": "curl -sI https://app.example.org"})
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={"decision": "silent", "reason": _REASON_19, "signal_draft": None},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run():
        started = FROZEN_AT
        if started.strftime("%H:%M") == "13:55":
            # The reason's clock time must not reach the payload by coincidence.
            started -= timedelta(minutes=2)
        return triage(
            Alert(
                fingerprint=_FINGERPRINT_19, status="firing",
                labels={"alertname": "ContainerRestartingExcessively", "severity": "critical"},
                annotations={"summary": "web-dashboard restarted more than 10 times in 1h"},
                starts_at=started.isoformat(),
                ends_at="0001-01-01T00:00:00Z",
            )
        )

    return SimpleNamespace(run=run, world=world, state=state)


def _the_pass_leaves_its_readings_and_its_reason_on_the_loop_triage(pod_19) -> None:
    pod_19.run()
    rows = [
        row for row in pod_19.state.message_evidence.said_between("0000", "9999")
        if row["loop"] == "triage"
    ]
    assert len(rows) == 1
    assert rows[0]["recipient"] == _FINGERPRINT_19
    assert any("HTTP/2 200" in reading["excerpt"] for reading in rows[0]["readings"])


def _a_critical_silenced_on_a_stamp_nothing_read_pages(pod_19) -> None:
    assert pod_19.run().decision == "page-raw"


def _a_critical_silenced_on_a_stamp_a_reading_carries_stays_silent(pod_19) -> None:
    pod_19.world["reading"] = "6f6f6f6f 2026-10-20T13:55:07Z web: pin APP_VERSION (48s)"
    assert pod_19.run().decision == "silent"

# From a triage silence never cites a page its fingerprint never delivered.

_CLAIM_20 = "same dead textfile service already paged and delivered at 03:17 UTC"


def _seed_20(state) -> None:
    """A delivered on its own fingerprint, B never."""
    state.record_alert(
        fingerprint=_COST_AUDIT, name="UnitFailed", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )
    for _ in range(2):
        state.record_alert(
            fingerprint=_GATE_AUDIT, name="UnitFailed", severity="warning",
            status="firing", decision="silent", reason=_CLAIM_20,
            signal_sent=False, dead_letter=False,
        )


@pytest.fixture()
def submit_silence(tmp_path, monkeypatch):
    """A fresh table with the two fingerprints, and a model stub that silences
    with the claim, optionally naming a covering fingerprint. Returns a call
    that triages one alert and the list of user messages the model was shown."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    _seed_20(state)
    shown: list[str] = []
    covering: dict[str, str | None] = {"fingerprint": None}

    def fake_run(*, messages, **_ignored):
        shown.append(messages[0]["content"])
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "silent", "reason": _CLAIM_20, "signal_draft": None,
                "covered_by_fingerprint": covering["fingerprint"],
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run(fingerprint: str, covered_by: str | None = None):
        covering["fingerprint"] = covered_by
        alert = Alert(
            fingerprint=fingerprint, status="firing",
            labels={"alertname": "UnitFailed", "severity": "warning"},
            annotations={"summary": "a systemd unit on the ops VM failed"},
            starts_at="2026-08-31T21:40:00Z", ends_at="0001-01-01T00:00:00Z",
        )
        return triage(alert)

    return SimpleNamespace(run=run, shown=shown, state=state)


def _a_claimed_page_on_a_fingerprint_that_never_delivered_pages(submit_silence) -> None:
    result = submit_silence.run(_GATE_AUDIT)
    assert result.decision == "page-raw"
    assert result.signal_draft
    assert "has ever reached a phone" in submit_silence.shown[0]


def _a_claimed_page_that_was_delivered_stands_with_the_time_code_read(submit_silence) -> None:
    delivered = next(
        row["signal_sent_at"]
        for row in submit_silence.state.list_recent_alerts(10)
        if row["fingerprint"] == _COST_AUDIT and row["signal_sent_at"]
    )
    result = submit_silence.run(_COST_AUDIT)
    assert result.decision == "silent"
    assert delivered
    # The time code read leads; the model's own words follow, quoted as they
    # came and labelled as the model's.
    assert result.reason.startswith(
        f"repeat; last delivered on this fingerprint at {delivered[:16]}Z (model said: "
    )
    assert f"last delivered to a phone at {delivered[:16]}Z" in submit_silence.shown[0]


def _cover_by_another_page_stands_only_when_that_page_was_delivered(submit_silence) -> None:
    covered = submit_silence.run(_GATE_AUDIT, covered_by=_COST_AUDIT)
    assert covered.decision == "silent"
    assert _COST_AUDIT in covered.reason


def _the_awareness_rows_tell_two_alerts_of_one_name_apart(submit_silence) -> None:
    from apps.assistant.core import awareness

    picture = awareness.render()
    assert f"UnitFailed [{_COST_AUDIT}]" in picture
    assert f"UnitFailed [{_GATE_AUDIT}]" in picture

# From a triage silence reason keeps its clock times and its counts come from the table.

_FINGERPRINT_21 = "9c620cfb66dd863e"


_REASON_21 = "Already paged on 2026-06-11 at 19:14. Silenced every cycle today (06:28, 10:28, 14:28)."


@pytest.fixture()
def pod_21(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, state, tools
    from apps.assistant.core.state.conn import get_connection
    from apps.assistant.core.triage import Alert, triage

    delivered = state.record_alert(
        fingerprint=_FINGERPRINT_21, name="TargetDown", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE alerts SET received_at = ?, signal_sent_at = ? WHERE id = ?",
            ("2026-06-11T19:14:00+00:00", "2026-06-11T19:14:00+00:00", delivered),
        )
        conn.commit()
    for reason in ("judged", "judged", "judged", "dedup-window-hit"):
        state.record_alert(
            fingerprint=_FINGERPRINT_21, name="TargetDown", severity="warning",
            status="firing", decision="silent", reason=reason,
            signal_sent=False, dead_letter=False,
        )
    shown: list[str] = []

    def fake_run(*, messages, **_ignored):
        shown.append(messages[0]["content"])
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={"decision": "silent", "reason": _REASON_21, "signal_draft": None},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    result = triage(
        Alert(
            fingerprint=_FINGERPRINT_21, status="firing",
            labels={"alertname": "TargetDown", "severity": "warning"},
            annotations={"summary": "No alert has been proved to reach a phone"},
            starts_at="2026-06-11T13:12:00Z", ends_at="0001-01-01T00:00:00Z",
        )
    )
    return SimpleNamespace(result=result, shown=shown)


def _the_stored_reason_keeps_the_models_clock_times(pod_21) -> None:
    assert pod_21.result.decision == "silent"
    assert "at 19:14." in pod_21.result.reason
    assert "(06:28, 10:28, 14:28)" in pod_21.result.reason


def _the_page_history_gives_local_time_and_a_counted_total(pod_21) -> None:
    assert "21:14 local time" in pod_21.shown[0]
    assert "silenced 3 times since" in pod_21.shown[0]

# From an all clear says when the alert stopped and never that the problem is gone.

_FINGERPRINT_22 = "5e6f7a8b9c0d1e2f"


_SUMMARY = (
    "A meeting has waited 30 minutes for a GPU and is not being transcribed "
    "(example-warmup-job)."
)


_CLAIMS_THE_PROBLEM_IS_GONE = re.compile(
    r"needs no action|\bclear(ed)?\b|\bfixed\b|\bresolved\b|back to normal|all good",
    re.IGNORECASE,
)


@pytest.fixture()
def resolve_after_a_page(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import state
    from apps.assistant.core.triage import Alert, triage

    state.record_alert(
        fingerprint=_FINGERPRINT_22, name="TargetDown", severity="critical",
        status="firing", decision="enrich", reason="fixture",
        signal_sent=True, dead_letter=False,
    )
    return lambda: triage(Alert(
        fingerprint=_FINGERPRINT_22, status="resolved",
        labels={"alertname": "TargetDown", "severity": "critical",
                "kind": "notulen-waiting"},
        annotations={"summary": _SUMMARY},
        starts_at="2030-07-10T15:41:00Z", ends_at="2030-07-10T16:41:00Z",
    ))


def _an_all_clear_says_when_the_alert_stopped_and_never_that_the_problem_is_gone(
    resolve_after_a_page,
) -> None:
    """It names the stop and its clock, and claims nothing about the problem."""
    draft = resolve_after_a_page().signal_draft

    assert draft, "a resolve of a delivered page must still reach the phone"
    assert "stopped firing" in draft.lower()
    assert "18:41" in draft
    found = _CLAIMS_THE_PROBLEM_IS_GONE.search(draft)
    assert not found, (
        f"the all-clear says {found.group(0)!r}, but an alert also stops when its "
        "subject goes away: the meeting was still waiting for a GPU"
    )

# From the weekly compact sees the commits of its window and is told to keep a hedge.

from apps.assistant.core import brain, compact, state as state_23


_FIX_SHA = "5e5e5e5e5e"


_ASKED_23: list[str] = []


_LAST_WEEK_END = (FROZEN_AT - timedelta(days=5)).replace(microsecond=123456)


def _fake_gh(args: list[str]) -> tuple[int, str, str]:
    """GitHub as `changes` reads it: one commit on main, no issue changes."""
    if args[0] == "api":
        _ASKED_23.append(args[1])
        row = {"sha": _FIX_SHA, "message": "secret scan: drop the leaked test token",
               "at": "2030-01-15T09:05:00Z"}
        return 0, json.dumps(row) + "\n", ""
    return 0, "[]", ""


@pytest.fixture()
def captured(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state_23.reset_for_tests()
    _ASKED_23.clear()
    # The last compact's end as compact_week stores it: isoformat(), with
    # microseconds and "+00:00" (e.g. "2030-01-11T21:00:20.123456+00:00").
    state_23.add_compact(week_start="", week_end=_LAST_WEEK_END.isoformat(), text="before")
    state_23.add_note(
        "Cost 123.45, likely a billing-period reset artifact (new billing window).",
        source="patrol",
    )
    monkeypatch.setattr(compact._changes, "_run_gh", _fake_gh)
    monkeypatch.setattr(compact.budget, "is_tripped", lambda: False)
    seen: dict = {}

    def _run(*, system, messages, tools, cap):
        seen["system"] = system
        seen["user"] = messages[0]["content"]
        reply = SimpleNamespace(content=[SimpleNamespace(type="text", text="summary")])
        return brain.LoopOutcome(status="finished", response=reply)

    monkeypatch.setattr(compact._brain, "run", _run)
    return seen


def _the_summariser_sees_the_fix_commit(captured: dict) -> None:
    assert compact.compact_week() == "summary"
    assert _FIX_SHA in captured["user"], (
        "the commit that resolved the page never reached the summariser"
    )
    assert "likely a billing-period reset artifact" in captured["user"]


def _the_window_bound_reaches_github_as_utc_with_a_z(captured: dict) -> None:
    """The stored week end carries "+00:00", which a query string turns into a
    space; and a week holds far more than the 40 commits a report lists."""
    compact.compact_week()
    (query,) = _ASKED_23
    since = query.split("since=")[1].split("&")[0]
    assert since == _LAST_WEEK_END.strftime("%Y-%m-%dT%H:%M:%SZ"), query
    assert "+" not in since
    assert "per_page=100" in query, query


def _a_cut_commit_list_is_not_read_as_no_resolution(captured: dict) -> None:
    compact.compact_week()
    assert 'MORE EXIST or COULD NOT READ, write "not checked"' in captured["system"]


def _the_summariser_is_told_to_keep_hedges(captured: dict) -> None:
    compact.compact_week()
    system = captured["system"]
    assert "Keep a note's hedge" in system
    assert "no resolution only after checking" in system

# From triage names the worklist item a page concerns only from the open items its prompt shows it.

_ALEX_24 = "+15550100012"


_ITEM = 12


_TITLE = "example-api-key rotation guard is blind"


@pytest.fixture()
def pod_24(tmp_path, monkeypatch):
    """A fresh state DB with item 12 open, and a model stub that pages."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX_24}=Alex:founder:{_ALEX_24}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX_24)
    from apps.assistant.core import brain, self_context, state, tools

    state.reset_for_tests()
    for number in range(1, _ITEM):
        state.worklist.add_item("look_into", f"unrelated item {number}", owner="Alex")
    state.worklist.add_item("look_into", _TITLE, owner="Alex")
    stub: dict[str, object] = {"override": None}

    def fake_run(*, messages, **_ignored):
        turn = str(messages[0]["content"])
        shown = re.search(rf"item (\d+): {re.escape(_TITLE)}", turn)
        named = int(shown.group(1)) if shown else None
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "enrich",
                "reason": "rotation date missing",
                "signal_draft": "example-api-key has no rotation date, so its age alarm can never fire.",
                "worklist_item": stub["override"] if stub["override"] is not None else named,
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    return stub


def _triage(fingerprint: str):
    from apps.assistant.core.triage import Alert, triage

    return triage(Alert(
        fingerprint=fingerprint, status="firing",
        labels={"alertname": "TargetDown", "severity": "warning",
                "component": "secret-age", "secret": "example-api-key"},
        annotations={"summary": "example-api-key has no rotation date"},
        starts_at="2026-03-10T10:00:00Z", ends_at="0001-01-01T00:00:00Z",
    ))


def _a_page_about_an_open_item_concerns_the_id_the_model_read_in_its_turn(pod_24) -> None:
    """The stub can only name 12 by reading it out of the turn triage built."""
    result = _triage("9dd4a93b4a18b053")
    assert result.worklist_items == (_ITEM,), (
        f"the page concerns {result.worklist_items}; the turn should have shown item {_ITEM}"
    )


def _an_id_no_open_item_has_is_dropped(pod_24) -> None:
    """A guessed id that is not an open item never reaches the relay."""
    pod_24["override"] = 999
    result = _triage("1c0ffee000000001")
    assert result.worklist_items == (), f"a guessed id survived: {result.worklist_items}"

# From a page triage ties to a worklist item reaches the relay feed as concerning that item.

_SECRET = "test-bearer"


_ALEX_25 = "+15550100012"


_ITEM_25 = 36


def _envelope(fingerprint: str) -> dict:
    return {
        "version": "4",
        "status": "firing",
        "alerts": [{
            "status": "firing",
            "labels": {
                "alertname": "TargetDown", "severity": "warning",
                "component": "secret-age", "secret": "anthropic-api-key",
            },
            "annotations": {"summary": "anthropic-api-key has no rotation date"},
            "startsAt": "2026-10-22T10:00:00Z", "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": fingerprint,
        }],
    }


@pytest.fixture()
def pod_25(tmp_path, monkeypatch):
    """A fresh state DB holding item 36, a model stub that pages, and a Signal stub."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX_25}=Alex:founder:{_ALEX_25}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX_25)
    from fastapi.testclient import TestClient

    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.gates import app as gate_app

    state.reset_for_tests()
    for number in range(1, _ITEM_25 + 1):
        state.worklist.add_item("look_into", f"item {number}", owner="Alex")
    named: dict[str, object] = {"item": None}

    def fake_run(**_ignored):
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "enrich",
                "reason": "rotation date missing",
                "signal_draft": "anthropic-api-key has no rotation date, so its age alarm can never fire.",
                "worklist_item": named["item"],
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda **_ignored: True)
    client = TestClient(gate_app.app)

    def page(fingerprint: str, item: int | None) -> dict:
        """Post one alert whose page names `item`, release it, and return the relayed send."""
        named["item"] = item
        response = client.post(
            "/webhook/alertmanager", json=_envelope(fingerprint),
            headers={"Authorization": f"Bearer {_SECRET}"},
        )
        assert response.status_code == 200, response.text
        # 14:00 local on a Thursday: outside quiet hours and past the morning gate.
        page_hold.release(now=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc))
        from apps.assistant.core import sent_feed

        return sent_feed.sends_after(0).sends[-1]

    return SimpleNamespace(page=page)


def _a_page_about_item_36_reaches_the_relay_marked_as_concerning_36(pod_25) -> None:
    """The page's item rides from the submit to the note the chat reads."""
    from apps.assistant.watch import chat_relay

    send = pod_25.page("9dd4a93b4a18b053", _ITEM_25)
    assert [item["id"] for item in send["concerns"]] == [_ITEM_25], (
        f"the page reached the relay concerning {send['concerns']}; it must concern {_ITEM_25}"
    )
    note = chat_relay.note(send)
    assert f"record_answer with item_id {_ITEM_25}" in note, f"the note names no call: {note!r}"


def _a_page_that_names_no_item_concerns_nothing(pod_25) -> None:
    """Control: a submit with no item gives a send with no item of its own."""
    send = pod_25.page("1c0ffee000000001", None)
    assert send["concerns"] == [], f"a page naming no item concerns {send['concerns']}"

# From a patrol question reaches the relay feed as concerning the worklist item its pass opened.

_ALEX_26 = "+15550100012"


_QUESTION = "Should the nightly backup keep 14 days or 30?"


@pytest.fixture()
def pod_26(tmp_path, monkeypatch):
    """A fresh state DB, a bearer, a patrol model stub that files and asks, and a landing send."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX_26}=Alex:founder:{_ALEX_26}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX_26)
    from fastapi.testclient import TestClient

    from apps.assistant.core import patrol, state
    from apps.assistant.gates import app as gate_app

    state.reset_for_tests()
    untouched = state.worklist.add_item("watch", "Registry size", owner="Alex")
    filed: dict[str, int] = {}

    def fake_run(**kwargs):
        bookkeeping = kwargs["dispatch"](
            "manage_worklist",
            {"action": "add", "kind": "watch", "title": "Backup bucket size"},
        )
        filed["watch"] = int(re.search(r"worklist item (\d+)", bookkeeping).group(1))
        answer = kwargs["dispatch"](
            "manage_worklist",
            {"action": "add", "kind": "question", "title": "Backup retention: 14 or 30 days"},
        )
        filed["id"] = int(re.search(r"worklist item (\d+)", answer).group(1))
        return SimpleNamespace(
            finished=True,
            status="finished",
            response=SimpleNamespace(content=[SimpleNamespace(type="text", text=_QUESTION)]),
        )

    monkeypatch.setattr(patrol._brain, "run", fake_run)
    monkeypatch.setattr(patrol._self_context, "render", lambda *a, **k: "system")
    monkeypatch.setattr(patrol._quiet_hours, "quiet_now", lambda *a, **k: False)
    monkeypatch.setattr(gate_app.openclaw_issue_sweep, "sweep_orphan_issues", lambda: [])
    monkeypatch.setattr(gate_app.openclaw_recurring, "file_recurring_observations", lambda: [])
    monkeypatch.setattr(gate_app, "_send_beat", lambda body: True)
    client = TestClient(gate_app.app)
    return SimpleNamespace(client=client, filed=filed, untouched=untouched)


def _the_question_reaches_the_relay_concerning_the_item_it_filed(pod_26) -> None:
    """The item the pass opened rides with its line to the note the chat reads."""
    from apps.assistant.watch import chat_relay
    from apps.assistant.core import sent_feed

    response = pod_26.client.post("/webhook/patrol", headers={"Authorization": f"Bearer {_SECRET}"})
    assert response.status_code == 200 and response.json()["sent"], response.text

    send = sent_feed.sends_after(0).sends[-1]
    assert send["text"] == _QUESTION, send
    assert [item["id"] for item in send["concerns"]] == [pod_26.filed["id"]], (
        f"the patrol question concerns {send['concerns']}; it must concern the "
        f"item its pass opened, {pod_26.filed['id']}"
    )
    note = chat_relay.note(send)
    assert f"record_answer with item_id {pod_26.filed['id']}" in note, note
    assert f"[{pod_26.untouched}]" not in note, f"the note offers the untouched item: {note!r}"
    assert f"item_id {pod_26.filed['watch']}" not in note, (
        f"the note names the watch item the pass filed as bookkeeping: {note!r}"
    )

# From alerts of one shared scrape path in an envelope are triaged once held as one page and all read delivered when it lands.

_TUNNEL = [
    ("probes-tls", "https://alerts.example.org", "c408782c00000001"),
    ("probes-tls", "https://metrics.example.org", "7cf53cfba607fb7a"),
    ("probes-health", "https://docs.example.org/healthz", "2fd5916c58edc4c3"),
    ("probes-health", "https://status.example.org/healthz", "5164a40900000002"),
    ("probes-http", "https://app.example.org/", "b0228d9600000003"),
    ("probes-http", "https://example.org/", "0e1d2c3b4a596877"),
]


_LONE = ("app-exporter", "app-exporter:8000", "9c620cfb66dd863e")


_LEADER = min(fingerprint for _, _, fingerprint in _TUNNEL)


def _alert(job: str, instance: str, fingerprint: str, via: str | None) -> dict:
    labels = {
        "alertname": "TargetDown", "severity": "warning",
        "component": "scrape-target", "job": job, "instance": instance,
    }
    if via:
        labels["scrape_via"] = via
    return {
        "status": "firing", "labels": labels,
        "annotations": {"summary": f"Prometheus target {job}/{instance} down 15m"},
        "startsAt": "2026-10-22T14:00:00Z", "endsAt": "0001-01-01T00:00:00Z",
        "fingerprint": fingerprint,
    }


def _envelope_27(tunnel: list[tuple[str, str, str]]) -> dict:
    alerts = [_alert(*entry, via="k8s-tunnel") for entry in tunnel]
    alerts.append(_alert(*_LONE, via=None))
    return {"version": "4", "status": "firing", "alerts": alerts}


@pytest.fixture()
def pod_27(tmp_path, monkeypatch):
    """A fresh table, a bearer, a model stub that pages, and a Signal stub."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    from fastapi.testclient import TestClient

    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.gates import app as gate_app

    calls: list[str] = []

    def fake_run(*, messages, **_ignored):
        calls.append(messages[0]["content"])
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "enrich", "reason": "targets dark",
                "signal_draft": f"Scrape targets dark ({len(calls)}).",
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda **_ignored: True)
    client = TestClient(gate_app.app)

    def post(tunnel: list[tuple[str, str, str]]):
        response = client.post(
            "/webhook/alertmanager", json=_envelope_27(tunnel),
            headers={"Authorization": f"Bearer {_SECRET}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return SimpleNamespace(post=post, calls=calls, state=state, page_hold=page_hold)


def _one_cause_is_one_model_call_and_one_held_page(pod_27) -> None:
    pod_27.post(_TUNNEL)
    assert len(pod_27.calls) == 2
    held = pod_27.state.pending_pages()
    assert sorted(row["key"] for row in held) == sorted([_LEADER, _LONE[2]])
    followers = [
        row for row in pod_27.state.list_recent_alerts(50)
        if row["reason"] == f"same cause as {_LEADER}"
    ]
    assert len(followers) == len(_TUNNEL) - 1


def _a_resend_in_another_order_folds_into_the_same_held_page(pod_27, monkeypatch) -> None:
    monkeypatch.setattr(pod_27.state, "dedup_check_and_touch", lambda fingerprint: False)
    pod_27.post(_TUNNEL)
    pod_27.post(list(reversed(_TUNNEL)))
    keys = {row["key"] for row in pod_27.state.pending_pages()}
    assert keys == {_LEADER, _LONE[2]}


def _every_fingerprint_of_the_cause_reads_delivered_once_the_page_lands(pod_27) -> None:
    from apps.assistant.core.state.alerts import last_delivered_at

    pod_27.post(_TUNNEL)
    # 14:00 local: outside quiet hours and past the morning gate.
    pod_27.page_hold.release(now=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc))
    for _, _, fingerprint in _TUNNEL:
        assert last_delivered_at(fingerprint), fingerprint


def _the_leader_recovering_alone_does_not_drop_the_group_page(pod_27) -> None:
    pod_27.post(_TUNNEL)
    pod_27.state.record_alert(
        fingerprint=_LEADER, name="TargetDown", severity="warning",
        status="resolved", decision="silent", reason="fixture",
        signal_sent=False, dead_letter=False,
    )
    pod_27.page_hold.release(now=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc))
    assert pod_27.state.last_released_text(_LEADER), "the group page was dropped"

# From every house rule reaches assistants voice.



from apps.assistant.shared.name import ASSISTANT_NAME


import pathlib


from apps.assistant.core import voice


_SOUL = pathlib.Path(__file__).resolve().parents[3] / ".claude" / "soul.md"


def _house_bullets() -> list[str]:
    """The bullets of the house soul, as the repository writes them."""
    return [
        bullet.rstrip()
        for bullet in re.split(r"^- ", _SOUL.read_text(), flags=re.MULTILINE)[1:]
    ]


def _every_house_rule_reaches_assistants_voice() -> None:
    """Each bullet is in the rendered voice, word for word, except the one
    The assistant replaces."""
    rendered = voice.render()
    missing = []
    for bullet in _house_bullets():
        if bullet.startswith(voice._ENGLISH_ONLY):
            continue
        wanted = " ".join(bullet.replace(voice._GLOSSARY_CLAUSE, "").split())
        if wanted not in " ".join(rendered.split()):
            missing.append(bullet[:60])
    assert not missing, (
        f"the house voice and {ASSISTANT_NAME}'s voice have drifted again; these rules are "
        f"in .claude/soul.md and not in the render: {missing}"
    )


def _the_two_swaps_are_the_only_ones() -> None:
    """The English-only rule is gone and the assistant's language rule is in its place,
    and the glossary clause the assistant has no tool for does not survive."""
    rendered = voice.render()
    assert voice._ENGLISH_ONLY not in rendered, (
        f"{ASSISTANT_NAME} is being told to write English only, which would send Robin "
        "English"
    )
    assert "in their language" in rendered, "the language rule that replaces it is gone"
    assert "add it to CONTEXT.md" not in rendered, (
        f"{ASSISTANT_NAME} is being told to write a file it has no tool for"
    )


def _the_soul_still_carries_exactly_one_english_only_rule() -> None:
    """The swap is keyed on that rule's opening words, so a reworded house
    soul must fail here rather than silently sending a teammate English."""
    opens_with_it = [
        bullet for bullet in _house_bullets()
        if bullet.startswith(voice._ENGLISH_ONLY)
    ]
    assert len(opens_with_it) == 1, (
        f".claude/soul.md carries {len(opens_with_it)} rules opening with "
        f"{voice._ENGLISH_ONLY!r}; voice.py swaps exactly one and a person has "
        "to re-decide the swap"
    )

# From a write nobody asked for is booked to assistant and never borrows the rights.

from starlette.applications import Starlette


from starlette.routing import Route


from starlette.testclient import TestClient


from apps.assistant.core import state as state_29


from apps.assistant.core.tools.team import message_teammate


from apps.assistant.gates import mcp


_BEARER = "door-test-bearer"


_PEOPLE = "uuid:alex-uuid=Alex:dev:+15550100001"


@pytest.fixture()
def door(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A live door over a real state database; sends and dispatches recorded."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _BEARER)
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setenv("ASSISTANT_GITHUB_WRITE", "1")
    state_29.reset_for_tests()
    sent: list[str] = []
    dispatched: list[str] = []
    real_dispatch = mcp.write_tools.dispatch

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append(message)
        return True

    def _dispatch(name, tool_input, actor):
        dispatched.append(name)
        if name == mcp.write_tools.GITHUB_ACT:
            return "commented on #151"
        return real_dispatch(name, tool_input, actor)

    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: True)
    monkeypatch.setattr(mcp.write_tools, "dispatch", _dispatch)
    built = mcp.assistant_mcp_door()
    app = Starlette(
        routes=[Route("/mcp", built.asgi_app, methods=["POST"])],
        lifespan=built.lifespan,
    )
    with TestClient(app) as client:
        yield client, sent, dispatched


def _call(client: TestClient, tool: str, arguments: dict) -> str:
    """One `tools/call` over the door, answered as its text."""
    response = client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {_BEARER}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        content=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["content"][0]["text"]


def _a_worklist_item_assistant_opens_itself_is_recorded_as_assistants(door) -> None:
    """Owner and audit row both say assistant, not a teammate."""
    client, _sent, _dispatched = door
    answer = _call(
        client,
        "manage_worklist",
        {"action": "add", "kind": "watch", "title": "catering 47 agreement", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert "tracking as worklist item" in answer, answer
    owners = [item["owner"] for item in state_29.worklist.open_items()]
    assert owners == ["assistant"], owners
    door_rows = [row for row in state_29.assistant_actions.recent_actions() if row["kind"] == "door_write"]
    assert [row["actor"] for row in door_rows] == ["assistant"], door_rows


def _a_message_assistant_starts_itself_is_held_by_quiet_hours(door) -> None:
    """The self-actor's hold comes with the name."""
    client, sent, _dispatched = door
    answer = _call(
        client,
        "message_teammate",
        {"person": "Alex", "message": "The supplier contract waits on you.", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert "quiet hours" in answer, answer
    assert sent == []


def _a_board_write_booked_to_assistant_reaches_github_act(door) -> None:
    """the assistant on its own may work the board: the write is dispatched."""
    client, _sent, dispatched = door
    answer = _call(
        client,
        "github_act",
        {"action": "comment", "issue_number": 151, "body": "noted", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert mcp.write_tools.GITHUB_ACT in dispatched, answer
    assert "Nothing was written" not in answer, answer


def _naming_assistant_still_cannot_create_a_video_call(door) -> None:
    """A person-only write booked to the assistant is refused undispatched."""
    client, _sent, dispatched = door
    answer = _call(
        client,
        "create_video_call",
        {"title": "y", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert mcp.write_tools.CREATE_VIDEO_CALL not in dispatched, answer
    assert "Nothing was written" in answer, answer

# From a page leaves for a person with every utc time written on local on both sides of the october change.

from apps.assistant.shared import local_time, signal as signal_30


_SUMMER = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)


_CHANGE_DAY = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)


_WINTER = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)


def _every_utc_shape_is_written_on_locals_summer_clock() -> None:
    """The four shapes a model or a receipt writes, the day before the change."""
    text = (
        "down since 14:12 UTC, first seen 14:12:05 UTC, retried 14:20Z; "
        "deploy 2026-10-24T13:01:00Z"
    )
    assert local_time.in_local_time(text, _SUMMER) == (
        "down since 16:12 local time (CEST), first seen 16:12:05 local "
        "time (CEST), retried 16:20 local time (CEST); "
        "deploy 15:01:00 local time (CEST)"
    )


def _a_utc_time_after_the_change_is_written_on_the_winter_clock() -> None:
    """A page written in October, had it been sent after the change."""
    assert (
        local_time.in_local_time("status dashboard down since 13:56 UTC", _WINTER)
        == "status dashboard down since 14:56 local time (CET)"
    )


def _on_the_day_of_the_change_each_time_takes_its_own_offset() -> None:
    """02:30 happens twice on 25 October; the zone name tells the two apart."""
    assert local_time.in_local_time("00:30 UTC, then 01:30 UTC", _CHANGE_DAY) == (
        "02:30 local time (CEST), then 02:30 local time (CET)"
    )


def _a_range_marked_utc_once_moves_both_ends_and_keeps_its_length() -> None:
    """"14:00-15:00 UTC" is one hour; converting only the marked end made it three."""
    assert local_time.in_local_time("window 14:00\u201315:00 UTC", _SUMMER) == (
        "window 16:00\u201317:00 local time (CEST)"
    )
    assert local_time.in_local_time("between 14:00 and 15:00 UTC", _SUMMER) == (
        "between 16:00 and 17:00 local time (CEST)"
    )
    assert local_time.in_local_time("00:30-01:30 UTC", _CHANGE_DAY) == (
        "02:30 local time (CEST)-02:30 local time (CET)"
    )


def _a_link_or_code_span_in_the_message_passes_through_byte_for_byte() -> None:
    """A URL or a quoted field is a value someone copies, not prose."""
    link = "see https://x/?t=13:01:00Z at 14:12 UTC"
    assert local_time.in_local_time(link, _SUMMER) == (
        "see https://x/?t=13:01:00Z at 16:12 local time (CEST)"
    )
    code = "the rule fired: `startsAt: 2026-10-24T13:01:00Z`"
    assert local_time.in_local_time(code, _SUMMER) == code


def _a_dated_stamp_from_another_day_keeps_its_date() -> None:
    """The whats_changed stamp of 15 October, read on a winter morning."""
    assert local_time.in_local_time("2026-10-14T18:08:50Z 7a7a7a7a7a", _WINTER) == (
        "14 Oct 20:08:50 local time (CEST) 7a7a7a7a7a"
    )


def _a_time_the_model_already_converted_is_said_once() -> None:
    """Its own UTC echo in brackets collapses into the local time it wrote."""
    assert (
        local_time.in_local_time("since 16:12 local time (CEST) (14:12 UTC)", _SUMMER)
        == "since 16:12 local time (CEST)"
    )
    assert (
        local_time.in_local_time("since 16:12 local time (CEST) (14:12:00 UTC)", _SUMMER)
        == "since 16:12 local time (CEST)"
    )
    assert local_time.in_local_time("since 16:12 CEST (14:12 UTC)", _SUMMER) == (
        "since 16:12 CEST"
    )
    # A bracket naming a different moment is a second fact, not an echo.
    assert local_time.in_local_time("since 16:12 CEST (14:40 UTC)", _SUMMER) == (
        "since 16:12 CEST (16:40 local time (CEST))"
    )


def _a_time_naming_no_zone_or_another_offset_is_left_alone() -> None:
    """Nothing may guess the clock a bare time was read off."""
    text = "at 14:12, release 1.14:12Z, and 14:12 UTC+2"
    assert local_time.in_local_time(text, _SUMMER) == text


def _the_send_seam_rewrites_a_person_page_and_passes_a_machine_page_through(
    monkeypatch,
) -> None:
    """What `shared.signal.send` hands the transport, for each kind of send."""
    reached: list[tuple[str, str]] = []

    def transport(subject: str, body: str, *, recipient: str | None = None) -> bool:
        reached.append((subject, body))
        return True

    monkeypatch.setattr(signal_30, "_send_signal_raw", transport)
    stamp = "2026-10-26T13:56:00Z"
    assert signal_30.send("", f"down since {stamp}")
    assert signal_30.send("[RAW] ScoreDown", f"startsAt {stamp}")
    person, machine = reached
    assert person[0] == "" and "14:56:00 local time (CET)" in person[1]
    assert stamp not in person[1]
    assert machine == ("[RAW] ScoreDown", f"startsAt {stamp}")

# From a message assistant cannot back never reaches a phone.

from apps.assistant.shared.zone import LOCAL_ZONE_NAME


import importlib


from apps.assistant.core import claims, patrol


from apps.assistant.core.limits import SIGNAL_MAX_CHARS


from apps.assistant.core.signal_text import split_for_signal


# The write tools a chat turn declares. Written out as the plain strings the
# LLM surface publishes rather than imported from `core.tools.write_tools`,
# so the expectations below stand on the tool's NAME, which is the contract,
# and not on a constant the guard also reads.
CALENDAR_TOOL = "agenda_act"


CHAT_WRITE_TOOLS = {"agenda_act", "message_teammate", "github_act"}


# The people registry, in the exact `SIGNAL_PEOPLE` grammar the container's secret
# uses: `uuid:<id>=Name:role:+E164`. This is configuration the module reads
# from the environment on every call, not a stand-in for any code under test.
PEOPLE = (
    "uuid:alex-uuid=Alex:dev:+15550100001,"
    "uuid:sam-uuid=Sam:dev:+15550100015,"
    "uuid:robin-uuid=Robin:legal"
)


ALEX_PHONE = "+15550100001"


SAM_PHONE = "+15550100015"


NOBODYS_PHONE = "+15550100016"


# A line addressed to a teammate, of the kind the patrol gate must not put on
# the owner's phone.
THE_MISADDRESSED_LINE = (
    "Sam, het verslag staat klaar in de repo. "
    "Wil je er even naar kijken?"
)


# The same teammate, spoken ABOUT rather than TO. This is what a patrol note is
# FOR, so a guard that holds this one has silenced the beat.
A_LINE_ABOUT_SAM = (
    "Sam pushed a fix to the deploy gate this morning and the cycle is green "
    "again."
)


@pytest.fixture
def registry(monkeypatch):
    """Point the people registry and the pinned recipient at a known team.

    Returns a setter so a case can move the phone the line is going to, which
    is the only variable the addressing rule turns on.
    """
    monkeypatch.setenv("SIGNAL_PEOPLE", PEOPLE)
    monkeypatch.setenv("SIGNAL_ALLOWLIST", "")

    def deliver_to(number: str) -> None:
        monkeypatch.setenv("SIGNAL_RECIPIENT", number)

    deliver_to(ALEX_PHONE)
    return deliver_to


# ── Confabulation: a write the assistant says it made ──────────────────────────────
def _a_booking_assistant_never_made_is_caught_before_it_is_confirmed() -> None:
    """Ask for a calendar event, draft "done", call no tool: that must nudge.

    The rule needs no recorded output to apply: the person asked for a write,
    the draft says the write happened, and no `agenda_act` succeeded this turn,
    so the draft is a lie and the guard must say which tool would have made it
    true. The user-visible failure is a meeting nobody is coming to.
    """
    request = ["can you put a sync with Sam in my calendar tomorrow at 10:00?"]
    draft = "Done, set for tomorrow at 10:00."

    nudge = claims.unbacked_write_claim(draft, request, [], CHAT_WRITE_TOOLS)

    assert nudge is not None, "a booking claimed with no successful write passed"
    assert CALENDAR_TOOL in nudge, (
        f"the nudge does not name the tool that would make the claim true: {nudge!r}"
    )


def _the_same_confirmation_passes_once_the_write_really_landed() -> None:
    """The honest half, and the half that keeps the guard usable.

    Byte-identical draft, byte-identical request, one successful `agenda_act`
    receipt: the claim is now backed and nothing may be nudged. A guard that
    fires here accuses the assistant of inventing work it actually did, which is
    what a widened claim regex does to every landed calendar move.

    The second half is the read-only surface: patrol carries no calendar tool,
    and a loop is never nudged about a tool it does not have.
    """
    request = ["can you put a sync with Sam in my calendar tomorrow at 10:00?"]
    draft = "Done, set for tomorrow at 10:00."

    assert (
        claims.unbacked_write_claim(draft, request, [CALENDAR_TOOL], CHAT_WRITE_TOOLS)
        is None
    ), "a claim backed by a successful write was nudged anyway"
    assert (
        claims.unbacked_write_claim(draft, request, [], {"github_act"}) is None
    ), "a loop with no calendar tool was nudged about the calendar"


def _one_receipt_cannot_back_a_claim_about_two_writes() -> None:
    """"Done, both removed." with one successful call is still a lie.

    Counting is the whole point: one write landed, the draft claims two, so one
    of the two events is still in the calendar and the person has been told it
    is gone. Two receipts back it and
    must pass, which is the same fixture proving the count is what is read and
    not the word "both".
    """
    request = ["can you remove both events from my agenda tomorrow?"]
    draft = "Done, both removed."

    assert (
        claims.unbacked_write_claim(draft, request, [CALENDAR_TOOL], CHAT_WRITE_TOOLS)
        is not None
    ), "a claim about two removals passed on one successful write"
    assert (
        claims.unbacked_write_claim(
            draft, request, [CALENDAR_TOOL, CALENDAR_TOOL], CHAT_WRITE_TOOLS
        )
        is None
    ), "two successful writes did not back a claim about two"


# ── Misdelivery: one person's message on another person's phone ────────────
def _a_line_written_to_one_teammate_is_held_back_from_another_phone(
    registry,
) -> None:
    """the original message, and the two lines that must NOT be held.

    A patrol pass writes free text with one destination, so the name at the
    front of it routes nothing. Addressed to a teammate and going to the owner's phone,
    the line must be held and the addressee named. Delivered to a teammate's own
    phone the same words are correct and must pass. And a line ABOUT a teammate going
    to the owner is a patrol note doing its job: holding that one would silence the
    beat, which is a worse failure than the one being fixed.
    """
    assert patrol.misaddressed_to(THE_MISADDRESSED_LINE) == "Sam", (
        "a line opening 'Sam,' was cleared for Alex's phone"
    )
    assert patrol.misaddressed_to(A_LINE_ABOUT_SAM) is None, (
        "a note ABOUT a teammate was held, so the beat has been silenced"
    )

    registry(SAM_PHONE)
    assert patrol.misaddressed_to(THE_MISADDRESSED_LINE) is None, (
        "a line to Sam was held on the way to Sam"
    )


def _a_recipient_the_registry_cannot_place_counts_as_the_wrong_reader(
    registry,
) -> None:
    """An addressee nobody confirmed is not a confirmed one.

    The pinned number belongs to no registry entry, so nothing establishes that
    the person being addressed is the person holding the phone. Holding the
    line costs a beat; sending it costs one teammate's message landing on
    another teammate's phone, which is what this guard exists for.
    """
    registry(NOBODYS_PHONE)

    assert patrol.misaddressed_to(THE_MISADDRESSED_LINE) == "Sam", (
        "an unresolvable recipient was treated as the addressee"
    )


# ── Plumbing: true, and not news ───────────────────────────────────────────
def _a_deploy_sha_in_a_message_is_caught_as_assistants_own_bookkeeping() -> None:
    """A commit sha is something the assistant knows and nobody acts on.

    The rule is about the READER, not about truth: a sha, a routing decision or
    a component count are all correct and none of them is anything a person on
    a phone does something about. The second draft is the same news said in the
    reader's terms and must pass untouched, because a guard that can suppress a
    real report is a bug.
    """
    assert (
        claims.own_plumbing("The deploy of 3f9a1c2 landed on the box at 09:02.")
        is not None
    ), "a deploy sha went out as news"
    assert (
        claims.own_plumbing(
            "The nightly backup did not run last night, the unit failed at 02:00."
        )
        is None
    ), "a real report was flagged as plumbing"


# ── The cap: long is split, never truncated ────────────────────────────────
def _pack_by_hand(words: list[str], limit: int) -> list[str]:
    """A greedy word-packer, written out here on purpose.

    Six lines of the plain definition ("break only at whitespace, fit as many
    words as the cap allows") rather than a call into `signal_text`. Building
    the expectation with the code under test would make this self-consistency,
    which is what the deleted suite was made of.

    One tie is left undefined: a piece landing on EXACTLY the cap. The fixtures
    below use words of one length chosen so no piece can, so the two
    implementations cannot disagree over a case neither of them decides.
    """
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= limit:
            current = candidate
        else:
            pieces.append(current)
            current = word
    pieces.append(current)
    return pieces


def _a_long_message_is_split_to_fit_and_loses_not_one_word() -> None:
    """Over the cap, a message goes out in pieces that fit, with all of it.

    Without a cap an autonomous beat can put a note of over two
    thousand characters out as one message. The fix has a
    failure mode of its own that is worse than the bug: a splitter that trims to
    fit drops the ask at the end of the note, and nobody would see it go
    missing. So all three hold here, every piece within the cap, the packing
    the plain greedy rule produces, and every word back in its original order.

    The words themselves carry nothing; the fixture is a length, built from
    nine-character words so no piece can land exactly on the cap.
    """
    words = [f"word{index:05d}" for index in range(380)]
    message = " ".join(words)
    assert len(message) > 2180, "the fixture is too short to need splitting"

    pieces = split_for_signal(message)
    by_hand = _pack_by_hand(words, SIGNAL_MAX_CHARS)

    # A vacuous pass would be the worst outcome here: it would read as the cap
    # holding while nothing was ever split.
    assert len(by_hand) >= 3, (
        f"the cap ({SIGNAL_MAX_CHARS}) no longer splits this message at all"
    )
    assert max(len(piece) for piece in pieces) <= SIGNAL_MAX_CHARS, (
        "a piece longer than the cap was handed to the sender"
    )
    assert " ".join(pieces).split() == words, (
        "the split lost, reordered or cut a word; a trimmed message is worse "
        "than a long one"
    )
    assert pieces == by_hand, (
        "the split does not pack greedily at whitespace: "
        f"{[len(piece) for piece in pieces]} against {[len(piece) for piece in by_hand]}"
    )


def _a_message_that_already_fits_goes_out_as_one_piece() -> None:
    """The normal case, and the other half of the cap.

    Almost every message the assistant sends is short. Splitting one of those into
    fragments reads as a stutter on a phone, so a message under the cap must
    come back whole, as a single piece, with only its surrounding whitespace
    gone.
    """
    note = "The backup ran at 02:00 and finished clean."

    assert split_for_signal(f"  {note}\n") == [note]


# ---------------------------------------------------------------------------
# The morning gate: one night of pings, one morning message.
#
# This section reaches for a temp SQLite file, which the header above says the
# rest of this file does not. The widening is deliberate and it is the smallest
# one available: the invariant is about WHEN a queue lets something go, and a
# queue with no state is not the thing under test. Nothing here sends, asks a
# model, or touches the container's real database; the send seam is replaced with a
# list so "reached a phone" is a number this file can count.
#
# The shape these cases are drawn from: the overnight hold works and no
# ping reaches the phone, then several composers each take their own turn
# within the hour, the first of them before the report it belonged in.
# ---------------------------------------------------------------------------
_LOCAL_TZ_31 = LOCAL_ZONE


def _at_31(hour: int, minute: int, day: int = 31) -> datetime:
    """One instant, local. Aware, because every gate under
    test converts to its own zone and a naive one would read as UTC, which is
    the two-hour slip that would move a 02:00 page into the afternoon."""
    return datetime(2026, 8, day, hour, minute, tzinfo=_LOCAL_TZ_31)


@pytest.fixture()
def phone_31(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue and a list standing in for the phone.

    Only the outermost seam is replaced: the Signal send. The gates, the fold,
    the pacing and the bookkeeping all run for real, because they are what
    decides whether a morning is one message or four.
    """
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    # No wait for the weekday brief: these cases pin the gate's clock,
    # and the brief carrying the night is pinned on its own.
    monkeypatch.setenv("ASSISTANT_BRIEF_WAIT_MINUTES", "0")
    from apps.assistant.core import page_hold

    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch, "send", lambda subject, body: landed.append(body) or True
    )
    return landed


def _a_night_of_pings_and_a_held_beat_reach_the_phone_as_one_message(phone_31) -> None:
    """The case this whole change exists for.

    A page written in the small hours and a beat written before breakfast: two
    composers, one message, not two sends, one when quiet hours end and one
    whenever the beat happens to fire.
    """
    from apps.assistant.core import page_hold, state

    state.hold_page("the night: 24 pings, the deploy queue is red", road="pen",
                    now=_at_31(2, 0).isoformat())
    # The old first message: the moment quiet hours end, and nothing may leave.
    assert page_hold.release(_at_31(7, 30)) is None
    page_hold.hold_beat("the deploy pipeline is gate-red this morning", subject="patrol")
    assert page_hold.release(_at_31(7, 45)) is None

    assert page_hold.release(_at_31(8, 0)) is not None

    assert len(phone_31) == 1
    message = phone_31[0]
    assert "24 pings" in message
    assert "gate-red" in message


def _a_patrol_finding_in_the_night_is_held_and_arrives_in_the_morning(
    phone_31, monkeypatch
) -> None:
    """An overnight finding, from the pass that finds it to the phone.

    A patrol that DROPS a line written inside quiet hours gives an overnight
    finding two possible fates, both wrong: the condition clears before
    morning and nobody is ever told, or it is still findable and the next pass
    reports it as present news about a container that has long been up again.

    The pass staying silent at night is not the bug and is not changed here.
    Everything except the model and the tool surface runs for real, because the
    thing under test is which road the finding takes.
    """
    from types import SimpleNamespace

    from apps.assistant.core import outbound, page_hold, state

    finding = "assistant-whisper stopped answering at 23:06"
    # Night for the pass, which asks with no moment, and for the 02:30 release;
    # morning for the 08:00 one. `page_hold` imports the same module, so a flat
    # True here would hold the morning too and the test would pin nothing.
    monkeypatch.setattr(
        patrol._quiet_hours, "quiet_now", lambda *a, **k: not a or a[0].hour < 8
    )
    monkeypatch.setattr(patrol._self_context, "render", lambda *a, **k: "system")
    monkeypatch.setattr(patrol, "_patrol_tool_definitions", lambda: [])
    monkeypatch.setattr(
        patrol._brain,
        "run",
        lambda **kwargs: SimpleNamespace(
            finished=True,
            status="finished",
            response=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=finding)]
            ),
        ),
    )

    # Nothing leaves at night, which was always right.
    assert patrol.patrol() is None
    assert page_hold.release(_at_31(2, 30)) is None

    assert page_hold.release(_at_31(8, 0)) is not None
    assert len(phone_31) == 1, "the morning was not one message"
    message = phone_31[0]
    assert finding in message, (
        "the overnight finding never reached the phone at all, which is the "
        "half of this failure nobody would ever have noticed"
    )
    assert re.search(r"Overnight, \d\d:\d\d:", message), (
        "a night reading reached the morning with no hour on it; that missing "
        "hour is what let it read as present news"
    )

    reasons = [row["reason"] for row in state.list_recent_alerts()]
    assert "quiet-hours-held" in reasons, "the audit row does not say it was held"
    assert "quiet-hours" not in reasons, (
        "the held finding is still recorded under the word that means lost"
    )
    assert "quiet-hours-held" in outbound.QUIET_REASONS, (
        "the reason is outside the closed vocabulary, so nobody can count it"
    )


def _a_night_nobody_reports_on_still_reaches_the_phone(phone_31) -> None:
    """The clock is the whole rule, and the reason it is not optional.

    It was the backstop under an issue, for a brief that runs Monday to Friday
    while this queue fills every day. No brief runs on a Saturday, so the
    deadline is what opens it. Without one a Saturday night would wait until
    Monday, which is a silence dressed as calm.
    """
    from apps.assistant.core import page_hold, state

    state.hold_page("a saturday night page", road="pen", now=_at_31(2, 0, day=29).isoformat())
    assert page_hold.release(_at_31(7, 30, day=29)) is None
    assert page_hold.release(_at_31(7, 59, day=29)) is None
    assert page_hold.release(_at_31(8, 0, day=29)) is not None
    assert len(phone_31) == 1


def _the_morning_gate_holds_nothing_outside_the_morning(phone_31) -> None:
    """An afternoon page leaves on the afternoon's rules.

    The gate is a stretch of clock, not a mode. Getting this wrong would hold
    every page all day, which is the same silent failure as holding the night
    for ever, just louder.
    """
    from apps.assistant.core import page_hold, state

    state.hold_page("an afternoon page", road="pen", now=_at_31(14, 0).isoformat())
    assert page_hold.release(_at_31(14, 0)) is not None


def _nothing_is_marked_sent_when_the_send_failed(phone_31, monkeypatch) -> None:
    """A page marked released that never arrived is the quiet failure this
    queue exists to make impossible, so a refused send keeps every row."""
    from apps.assistant.core import page_hold, state

    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda subject, body: False)
    # The failure's backoff lives in this throwaway, not in the next test.
    monkeypatch.setattr(page_hold, "_outage", page_hold._SendOutage())
    state.hold_page("a page nobody received", road="pen", now=_at_31(2, 0).isoformat())

    assert page_hold.release(_at_31(8, 0)) is None
    assert state.pending_page_count() == 1


def _the_pen_queues_its_night_page_instead_of_sending_it_at_half_seven(
    phone_31,
) -> None:
    """The pen's night page, on the road that produces it.

    The pen composes and sends on its own road, outside the shared brake, so
    a page it sends at 07:30 is untouched by everything else here unless it
    asks the gate the same question, which is what this pins. Inside the
    morning window it queues; outside it, it still sends on its own pacing,
    because a brake in front of a road that already paces itself is the second
    brake `page_hold` refuses to be.
    """
    from apps.assistant.core import notify_flush, page_hold, state

    assert notify_flush._morning_gate_shut(_at_31(7, 35)) is True
    assert notify_flush._morning_gate_shut(_at_31(14, 0)) is False

    notify_flush._hold_for_the_brief("the night: 24 pings, the deploy queue is red", [])
    assert page_hold.release(_at_31(7, 35)) is None, "the queued page must wait"
    assert not phone_31

    assert page_hold.release(_at_31(8, 0)) is not None
    assert len(phone_31) == 1
    assert "24 pings" in phone_31[0]

    # The clock opened it, and nothing is left behind.
    assert state.pending_page_count() == 0


# ---------------------------------------------------------------------------
# What a page reads like. An unreadable page that says little is four
# separate defects, and each of these pins one of them.
#
# The example batch: a collector unit failed at 05:30 local, and an audit
# unit plus the audit's own report both arrived at 04:40.
# ---------------------------------------------------------------------------
_TEXTFILE = "❌ [the project] systemd unit failed: example-collector.service"


_GATE_AUDIT_31 = "🟡 [the project] gate audit: the unselected suite is red"


_GATE_UNIT = "❌ [the project] systemd unit failed: example-audit.service"


def _ping(ping_id: int, subject: str, when: str, unit: str | None = None) -> dict:
    body = f"Host: harness-internal\nUnit: {unit}\n" if unit else "A body."
    return {
        "id": ping_id, "subject": subject, "body": body, "source": "notify",
        "received_at": when, "facts": '{"exit_code": 2}',
    }


def _page_31(pings: list[dict], *, lead: int, aspect: str, also=(), seen: int = 1,
          language: str = "en") -> str:
    from apps.assistant.core import page_render, ping_facts

    facts = ping_facts.bundle(pings, history_of=lambda _s: {"seen_count": seen})
    selection = page_render.Selection(
        verdict="page", lead=lead, aspect=aspect, also=tuple(also)
    )
    return page_render.render(selection, facts, language=language)


def _a_page_says_the_time_and_not_the_date_it_is_read_on() -> None:
    """A stamp on a page about this morning, read this morning.

    Not the full date and two clocks on every sentence:
    "2026-06-02 05:30 local (03:30 UTC)", three times in one page.
    """
    page = _page_31(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="failure",
    )
    assert "05:30" in page
    assert "2026-06-02" not in page
    assert "UTC" not in page


def _a_stamp_from_another_day_keeps_its_date() -> None:
    """The date goes only where the reader can supply it. Yesterday cannot be
    read off a page delivered today, so it is written."""
    page = _page_31(
        [_ping(3, _TEXTFILE, "2026-05-31T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="failure",
    )
    assert "31 May" in page
    assert LOCAL_ZONE_NAME.split("/")[-1] in page, "a dated stamp names the zone it is on"


def _a_count_is_said_in_words_or_not_at_all() -> None:
    """"Ping 2 on this subject" is this system counting its own rows out loud.

    A reader wants to know whether it is new or a repeat, so the count is a
    word, and it is only said from the second time on.
    """
    repeat = _page_31(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="escalation", seen=2,
    )
    assert "Second time on this subject" in repeat
    assert "Ping 2" not in repeat

    first = _page_31(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="first_seen", seen=1,
    )
    assert "time on this subject" not in first


def _the_unit_is_not_said_twice_when_the_subject_already_names_it() -> None:
    """The defect that made the page read as its own echo.

    A `unit_failed` sender puts the unit in its subject, so the page said
    "systemd unit failed: example-collector.service ... unit
    example-collector.service". The host is not in the subject and survives.
    """
    page = _page_31(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="failure",
    )
    assert page.count("example-collector.service") == 1
    assert "harness-internal" in page, "the host is not a repeat and stays"


def _two_pings_arriving_together_are_one_sentence() -> None:
    """Riders sharing a moment said once, with both subjects named.

    Not "Also in this batch: ..." twice, each with its own copy of the same
    stamp. Neither subject may be lost to the fold: a page never drops
    a ping to save a repetition.
    """
    page = _page_31(
        [
            _ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service"),
            _ping(1, _GATE_AUDIT_31, "2026-06-02T02:40:26+00:00"),
            _ping(2, _GATE_UNIT, "2026-06-02T02:40:26+00:00", "example-audit.service"),
        ],
        lead=3, aspect="failure",
        also=((1, "also_firing"), (2, "also_firing")),
    )
    assert page.count("Also") == 1
    assert page.count("04:40") == 1
    assert "the unselected suite is red" in page
    assert "example-audit.service" in page


def _riders_at_different_moments_are_not_folded_together() -> None:
    """The fold is about one moment. Two riders that arrived an hour apart are
    two facts, and merging them would put one of them at the wrong time."""
    page = _page_31(
        [
            _ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service"),
            _ping(1, _GATE_AUDIT_31, "2026-06-02T02:40:26+00:00"),
            _ping(2, _GATE_UNIT, "2026-06-02T01:10:00+00:00", "example-audit.service"),
        ],
        lead=3, aspect="failure",
        also=((1, "also_firing"), (2, "also_firing")),
    )
    assert "04:40" in page and "03:10" in page


# ── Filing a meeting on the board ────────────────────────────────
# The assistant writes to the board without asking now: the send button on the
# dashboard is the team's approval. So the guards worth having are the two
# that bound what a wrong reading can cost, and both are decidable by hand.
#: The action items table and decisions list of a meeting written to the
#: template, plus the empty row the template ships with.
_REAL_MINUTES = """\
# Meeting: Website relaunch, intake

## Discussed

### 1. Background
- Not a decision and not an action; this section must contribute nothing.

## Decisions

1. The relaunch goes live after the content review.
2. Robin checks the hosting quote with the supplier.
3. A fixed review window is planned for the copy.
4. Licences for the photos are bought under the standard agreement.

---

## Action items

| Action | Who | Deadline |
|---|---|---|
| Send the supplier the link to the brief | Jordan | End of day |
| Fill in the brief through the link Jordan sent | Supplier | Before the kick-off |
| Mail the supplier the kick-off details | Alex | End of day |
| | | |

## Next meeting

**Date**: to be planned
"""


def _how_many_issues_a_meeting_opens_is_read_and_not_judged() -> None:
    """Three action points and four decisions, counted by eye off the table.

    This is the number that decides how much a meeting writes to the board,
    so it is deliberately not the model's to choose: `parse_minutes` reads
    the template the project controls and the model is handed the result. The
    known answer is the document above, which anybody can count.

    The empty row matters as much as the full ones. The template ships with
    one, every meeting with fewer action points than the writer expected
    leaves one, and an empty row that became an issue would be a card with no
    title assigned to somebody. The bullet under `## Discussed` matters for
    the mirror reason: a discussion point is not a decision, and a parser
    that swept the whole document would turn every meeting into a backlog.
    """
    from apps.assistant.core.notulen import parse_minutes

    minutes = parse_minutes(_REAL_MINUTES, title="Website relaunch", meeting_date="2026-08-25")

    assert [action.who for action in minutes.actions] == ["Jordan", "Supplier", "Alex"], (
        "the action items table has three rows with an action in them; the "
        "fourth is the template's empty row and is not an issue"
    )
    assert minutes.actions[0].deadline == "End of day"
    assert len(minutes.decisions) == 4, (
        f"four numbered decisions, got {len(minutes.decisions)}: "
        f"{minutes.decisions}"
    )
    assert not any("Not a decision" in decision for decision in minutes.decisions), (
        "a bullet under Discussed is discussion, not a decision; sweeping the "
        "whole document would put every meeting's talk on the board"
    )
    assert not minutes.is_empty


def _a_meeting_can_only_land_on_something_that_is_open() -> None:
    """the assistant picks a parent from a list; it cannot type a number.

    It may open a new root when a meeting introduces a subject the board has
    no root for, which is the whole reason this is not gated behind a human.
    The cost of that freedom is bounded here: the tool's `parent` enum is 0
    (meaning "a new root") plus the open ROOTS, so a hallucinated number, a
    closed issue, or nesting under a child to make a fourth layer are not
    outcomes this path has. A decision may be commented onto any open issue,
    root or not, because a comment changes no structure.
    """
    from apps.assistant.core.notulen import Candidate, parse_minutes
    from apps.assistant.core.notulen.decide_placements import tool_definition

    minutes = parse_minutes(_REAL_MINUTES, title="Website relaunch", meeting_date="2026-08-25")
    board = [
        Candidate(53, "A deploy system nobody has to watch", "dev", True, False),
        Candidate(54, "notulen: edit the minutes", "dev", False, True),
        Candidate(151, "Dev-backlog", "dev", True, False),
    ]

    schema = tool_definition(minutes, board)["input_schema"]["properties"]
    parents = schema["actions"]["items"]["properties"]["parent"]["enum"]
    commentable = schema["comments"]["items"]["properties"]["issue"]["enum"]

    assert set(parents) == {0, 53, 151}, (
        f"parents offered were {parents}; #54 has a parent already, so "
        "nesting under it would make a fourth layer the board does not show"
    )
    assert set(commentable) == {53, 54, 151}
    # And it cannot open more cards than the meeting has action points.
    assert schema["actions"]["maxItems"] == 3
    assert schema["comments"]["maxItems"] == 4
    # Nor invent a department or an assignee.
    assert schema["actions"]["items"]["properties"]["assignee"]["enum"] == [
        "Alex", "Sam", "Robin", "Kim",
    ]


def _assistant_cannot_open_a_root_without_saying_what_it_checked() -> None:
    """A new root PRD needs its root check, in the container as well as in Claude.

    The root-check rule exists because a session can read its own prompt as a
    new workstream and open a second root for a subject that already has one.
    `.claude/hooks/issue_guard.py` enforces the root
    check on the Claude path and cannot run in this pod, and
    the assistant opens roots off its own bat when a meeting introduces a subject.
    So the same refusal lives in the tool, and it fires before any `gh` call.

    A PRD nested under a parent is not a root, and a plain issue never was.
    """
    from apps.assistant.core.tools.gh import github_act

    labels = ["PRD", "area:dev"]
    assert github_act._missing_root_check(labels, None, "## Goal\nSomething."), (
        "a root PRD with no root check must be refused; the repository "
        "refuses it on the other side anyway"
    )
    assert not github_act._missing_root_check(
        labels, None, "## Root check\nChecked #53; it covers deploys.\n\n## Goal\nx"
    )
    assert not github_act._missing_root_check(labels, 1, "## Goal\nx"), (
        "a PRD with a parent is not a root"
    )
    assert not github_act._missing_root_check(
        ["enhancement", "area:dev"], 151, "just a task"
    )


def _work_the_board_already_carries_is_not_opened_a_second_time() -> None:
    """A weekly meeting must not buy a new card for the same task every week.

    This is the failure mode that turns a board into a pile, and it is not
    hypothetical: a recurring meeting carries the same action point until it
    is done, and a meeting often agrees to something already tracked. There
    are two halves to stopping it, and only the second is checkable here.

    The model's half is a question it is asked first, with `already` to answer
    it in: an open issue that IS this action point. The Python half is that
    setting it writes a comment and opens nothing at all, so a wrong answer
    costs a comment on the wrong issue rather than a duplicate card with an
    owner. What is checked below is that second half plus the closure of the
    field, because a number the model made up would be a comment on somebody
    else's work.
    """
    from apps.assistant.core.notulen import Candidate, parse_minutes
    # Every deep-module file here is named after its one public callable
    # and the seam re-exports that callable, so the package attribute
    # `file_minutes` IS the function and a plain import gets the wrong
    # object. Reaching the module means asking importlib for it.
    filing = importlib.import_module(
        "apps.assistant.core.notulen.file_minutes"
    )
    from apps.assistant.core.notulen.decide_placements import (
        Placements,
        tool_definition,
    )

    minutes = parse_minutes(_REAL_MINUTES, title="Website relaunch", meeting_date="2026-08-25")
    board = [
        Candidate(53, "A deploy system nobody has to watch", "dev", True, False),
        Candidate(54, "notulen: edit the minutes", "dev", False, True),
    ]

    # Any open issue may be named as the one already carrying the work, root
    # or not, because work lives on children far more often than on roots.
    schema = tool_definition(minutes, board)["input_schema"]["properties"]
    already = schema["actions"]["items"]["properties"]["already"]
    assert already["enum"] == [None, 53, 54], (
        f"already offered {already['enum']}; it has to be closed over the open "
        "board, or a made-up number becomes a comment on somebody else's issue"
    )

    calls = []

    def _fake_execute(tool_input, actor="assistant"):
        calls.append(tool_input)
        return "done: https://github.com/owner/repo/issues/4242"

    plan = Placements(
        actions=[
            {"already": 54},
            {
                "title": "Send the assignment link", "body": "Jordan sends the supplier the link.",
                "parent": 53, "area": "dev", "assignee": "Alex",
            },
        ],
        comments=[],
        new_root=None,
    )
    filed = filing.Filed()
    real_execute = filing.github_act.execute
    filing.github_act.execute = _fake_execute
    try:
        filing._open_actions(plan, None, "https://example.invalid/minutes.md", filed)
    finally:
        filing.github_act.execute = real_execute

    assert [call["action"] for call in calls] == ["comment", "create"], (
        f"the two action points produced {[c['action'] for c in calls]}; the "
        "one the board already carries must be commented, never opened again"
    )
    assert calls[0]["issue_number"] == 54
    assert filed.updated == [54], "an updated issue is counted apart from a new one"
    assert filed.issues == [4242]
    assert not filed.problems

    # And the report says which is which, because "opened six issues" about a
    # meeting that opened one is how a board stops being believed.
    report = filed.as_report("Website relaunch")
    assert "#4242" in report and "#54" in report
    assert "already on the board" in report


def _an_action_point_that_is_neither_new_nor_known_is_left_off() -> None:
    """Nothing is required in the tool schema, so Python is the one that checks.

    An entry is one of two shapes: `already` alone, or a whole new issue. A
    half-filled one is a model mistake, and the cheap failure is a line in the
    report saying an action point was left off. The expensive one would be a
    card with no title on it, assigned to nobody, under a parent nobody chose.
    """
    # Every deep-module file here is named after its one public callable
    # and the seam re-exports that callable, so the package attribute
    # `file_minutes` IS the function and a plain import gets the wrong
    # object. Reaching the module means asking importlib for it.
    filing = importlib.import_module(
        "apps.assistant.core.notulen.file_minutes"
    )
    from apps.assistant.core.notulen.decide_placements import Placements

    calls = []
    real_execute = filing.github_act.execute
    filing.github_act.execute = lambda tool_input, actor="assistant": calls.append(tool_input)
    try:
        filed = filing.Filed()
        filing._open_actions(
            Placements(actions=[{"body": "half an answer"}], comments=[], new_root=None),
            None, "https://example.invalid/minutes.md", filed,
        )
    finally:
        filing.github_act.execute = real_execute

    assert calls == [], "a half-filled action point must reach GitHub as nothing"
    assert filed.issues == [] and filed.updated == []
    assert len(filed.problems) == 1 and "still" in filed.problems[0], (
        "the report has to say an action point was left off, and that the "
        "minutes still carry it"
    )


# ---------------------------------------------------------------------------
# The same question, twice.
#
# A teammate asks the assistant to arrange a call with the owner at 09:00. The
# assistant relays it, the owner answers with 10:00, the assistant books 10:00
# and tells the teammate. Putting the ORIGINAL 09:00 question to the owner
# again after that is the failure.
#
# The two messages below are a relay and its repeat, minutes apart. Both are
# good messages; the second is only wrong because the first exists. A check
# that reads one draft on its own cannot see the pair.
# ---------------------------------------------------------------------------
RELAY_FIRST = (
    "Sam asks whether you\'re up for a call tomorrow (Wednesday 2 Sep) at "
    "09:00. He\'s free then. If that works, I\'ll book it. This message is on "
    "Sam\'s request."
)


RELAY_AGAIN = (
    "Sam is asking whether you two can have a call tomorrow (Wednesday 2 Sep) "
    "at 09:00. This message is on Sam\'s request. Does that work for you?"
)


# A second message the same afternoon that is not the same message: a different
# time, and a different question.
RELAY_SOMETHING_NEW = (
    "Sam asks whether the Friday call can move to 14:00. This message is on "
    "Sam\'s request."
)


def _sent(text: str, at: str = "2026-06-02T14:49:47+00:00") -> dict:
    """One thing the assistant said to somebody, in the shape the chat store returns."""
    return {"role": "assistant", "text": text, "created_at": at}


def _the_question_alex_had_already_answered_is_not_asked_again() -> None:
    """A relay and its repeat, in the order they would be sent."""
    refusal = claims.repeated_message(RELAY_AGAIN, [_sent(RELAY_FIRST)], "Alex")

    assert refusal is not None, "the second 09:00 relay has to be caught"
    assert "16:49" in refusal, (
        "the refusal has to say when the first one went out, in local time, "
        "or the model cannot tell the requester what already happened"
    )


def _a_second_message_that_carries_something_new_still_goes() -> None:
    """The guard is about sameness, not about how many messages a subject may
    have. A different time and a different question is a different message, and
    refusing it would make this the guard somebody switches off."""
    assert claims.repeated_message(
        RELAY_SOMETHING_NEW, [_sent(RELAY_FIRST)], "Alex"
    ) is None


def _a_message_too_short_to_judge_is_never_called_a_repeat() -> None:
    """Below three distinctive terms one shared word carries the whole
    fraction, so the guard says nothing rather than something arbitrary."""
    assert claims.repeated_message("Booked, 10:00.", [_sent(RELAY_FIRST)], "Alex") is None


def _the_second_relay_never_reaches_the_phone(tmp_path, monkeypatch) -> None:
    """The wiring, not the predicate.

    The lesson of the attribution guard next to it is that a rule written in a
    docstring and checked nowhere is a rule the seam does not have. So this
    drives the real tool twice, with only the Signal send replaced, and counts
    what left the building.
    """
    from apps.assistant.core.tools.team import message_teammate

    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_TEAM_MESSAGE", "1")
    monkeypatch.setenv("SIGNAL_PEOPLE", PEOPLE)
    landed: list[str] = []
    monkeypatch.setattr(
        message_teammate._signal,
        "send",
        lambda subject, body, recipient=None: landed.append(body) or True,
    )

    first = message_teammate.execute(
        {"person": "Alex", "message": RELAY_FIRST}, actor="Sam"
    )
    again = message_teammate.execute(
        {"person": "Alex", "message": RELAY_AGAIN}, actor="Sam"
    )

    assert first == "messaged Alex."
    assert again.startswith("not sent:"), again
    assert landed == [RELAY_FIRST], "Alex\'s phone may only carry the one question"


def _a_new_question_after_a_refusal_still_goes_out(tmp_path, monkeypatch) -> None:
    """The other half: one refusal must not close the thread for the evening."""
    from apps.assistant.core.tools.team import message_teammate

    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_TEAM_MESSAGE", "1")
    monkeypatch.setenv("SIGNAL_PEOPLE", PEOPLE)
    landed: list[str] = []
    monkeypatch.setattr(
        message_teammate._signal,
        "send",
        lambda subject, body, recipient=None: landed.append(body) or True,
    )

    message_teammate.execute({"person": "Alex", "message": RELAY_FIRST}, actor="Sam")
    message_teammate.execute({"person": "Alex", "message": RELAY_AGAIN}, actor="Sam")
    third = message_teammate.execute(
        {"person": "Alex", "message": RELAY_SOMETHING_NEW}, actor="Sam"
    )

    assert third == "messaged Alex."
    assert landed == [RELAY_FIRST, RELAY_SOMETHING_NEW]


def _every_webhook_can_actually_reach_the_work_it_names() -> None:
    """A gate that imported the wrong object fails at the button, not at boot.

    A send-to-the-assistant button can answer 502 on its first real press:
    `from ...core.notulen import file_minutes as openclaw_notulen` followed
    by `openclaw_notulen.file_minutes(...)` fails. Every deep-module file in that package is named after its one public
    callable and the seam re-exports the callable, so that import hands back
    the function and asking it for `.file_minutes` is an AttributeError. It
    imports clean, it starts clean, and it raises the first time somebody
    uses it.

    The shape is general, so the check is: whatever a route calls as
    `<name>.<attr>(` has to be an attribute that exists and can be called.
    Import-time is the right place to find that, which is what this does.
    """
    import inspect
    import re

    from apps.assistant.gates import app

    source = inspect.getsource(app)
    # `filed = openclaw_notulen.file_minutes(` and its kind, inside the
    # route bodies rather than in the imports.
    called = set(
        re.findall(r"\b(openclaw_[a-z_]+)\.([a-z_]+)\(", source)
    )
    assert called, "no `openclaw_*.something(` call sites found; the check went blind"

    missing = []
    for name, attr in sorted(called):
        target = getattr(app, name, None)
        if target is None:
            missing.append(f"{name} is not imported at all")
        elif not callable(getattr(target, attr, None)):
            missing.append(
                f"{name}.{attr} is not callable ({type(target).__name__} "
                f"{getattr(target, '__name__', '')})"
            )
    assert not missing, (
        "a route names something it cannot call, so the request that reaches "
        "it fails and nothing before then does: " + "; ".join(missing)
    )


def _the_board_is_read_in_pages_github_will_actually_serve() -> None:
    """A read that asks for too much files nothing.

    GitHub's GraphQL connections refuse anything over 100 per page, with an
    error rather than a short answer. The caller then does the right thing
    with the wrong input: no board to read means no parent can be chosen, so
    it refuses to guess and files nothing, and a whole meeting reaches the
    board as one apologetic sentence on Signal.

    So the page size has to be one GitHub serves, and the ceiling has to be
    reached by paging rather than by asking for it all at once. Both are read
    off the module, and the second is what stops somebody "fixing" this by
    raising the page size back up.
    """
    reader = importlib.import_module(
        "apps.assistant.core.notulen.candidate_issues"
    )

    assert reader._PAGE <= 100, (
        f"a page of {reader._PAGE} is refused outright by GitHub; the whole "
        "board then reads as unreadable and the meeting is filed nowhere"
    )
    assert reader._LIMIT > reader._PAGE, (
        "the ceiling is meant to be reached by following pages; a limit "
        "inside one page means the paging is decoration"
    )
    assert "after:$after" in reader._QUERY and "hasNextPage" in reader._QUERY, (
        "the query has to carry a cursor and be asked whether more remain, "
        "or the board silently stops at the first page"
    )


def _only_a_root_is_offered_as_a_parent() -> None:
    """Read off real rows, because the shapes are what the board really has.

    A root is a PRD with no parent. Anything else is a child, and nesting
    under a child would make a fourth layer the board does not show. The
    filtering lives in the reader, so a candidate list that got it wrong would
    hand `decide_placements` a parent enum with children in it and the model
    would pick one sooner or later.
    """
    from apps.assistant.core.notulen.candidate_issues import Candidate

    rows = [
        {"number": 1, "title": "A root", "parent": None,
         "labels": {"nodes": [{"name": "PRD"}, {"name": "area:dev"}]}},
        {"number": 2, "title": "A child of it", "parent": {"number": 1},
         "labels": {"nodes": [{"name": "enhancement"}, {"name": "area:dev"}]}},
        {"number": 3, "title": "A PRD that got nested", "parent": {"number": 1},
         "labels": {"nodes": [{"name": "PRD"}]}},
    ]
    reader = importlib.import_module(
        "apps.assistant.core.notulen.candidate_issues"
    )

    built = [
        Candidate(
            number=int(row["number"]),
            title=row["title"],
            area=next(
                (label["name"].split(":", 1)[1] for label in row["labels"]["nodes"]
                 if label["name"].startswith("area:")), ""),
            is_root=("PRD" in [label["name"] for label in row["labels"]["nodes"]]
                     and not row.get("parent")),
            has_parent=bool(row.get("parent")),
        )
        for row in rows
    ]
    assert [c.number for c in built if c.is_root] == [1], (
        "only the PRD with no parent is a root; a PRD that drifted under a "
        "parent is not one, whatever its label says"
    )
    assert reader._PRD_LABEL == "PRD"


def _a_choice_outside_what_was_offered_is_dropped_not_written() -> None:
    """The enums make a good answer likely; this makes a bad one harmless.

    A tool-schema enum is guidance to the model, not a rule the API enforces:
    a model can answer `parent: 52` for two action points when that issue is
    not a root, it carries `enhancement` and sits under another issue, so both
    cards would land as a fourth layer the board does not show. Enums without
    checking is the mistake
    `page_render` names out loud: the enums can only remove refusals, and the
    Python parse is the only enforcer.

    Every dropped item is named rather than quietly lost, because it is still
    in the minutes and the person who pressed the button has to be told.
    """
    from apps.assistant.core.notulen import Candidate
    from apps.assistant.core.notulen.decide_placements import (
        NEW_ROOT,
        _only_what_was_offered,
    )

    board = [
        Candidate(1, "Operations: suppliers and contracts", "finance", True, False),
        Candidate(52, "Supplier contracts", "finance", False, True),
    ]
    chosen = {
        "actions": [
            {"title": "Under a child", "body": "b", "parent": 52,
             "area": "finance", "assignee": "Alex"},
            {"title": "Under a root", "body": "b", "parent": 1,
             "area": "finance", "assignee": "Alex"},
            {"title": "A made-up parent", "body": "b", "parent": 999999,
             "area": "finance", "assignee": "Alex"},
            {"title": "A department that is not one", "body": "b", "parent": 1,
             "area": "marketing", "assignee": "Alex"},
            {"title": "Somebody who does not work here", "body": "b", "parent": 1,
             "area": "finance", "assignee": "Jordan"},
            {"already": 52},
            {"already": 999999},
            {"title": "A new root", "body": "b", "parent": NEW_ROOT,
             "area": "finance", "assignee": "Alex"},
        ],
        "comments": [{"issue": 52, "body": "x"}, {"issue": 999999, "body": "x"}],
        "new_root": {"title": "t", "goal": "g", "root_check": "c",
                     "area": "nonsense", "assignee": "Alex"},
    }

    kept = _only_what_was_offered(chosen, board)

    assert [action.get("title") for action in kept.actions] == [
        "Under a root", None, "A new root",
    ], (
        "only a root, an `already` that is open, and the new-root marker may "
        f"survive; got {[a.get('title') or a.get('already') for a in kept.actions]}"
    )
    assert kept.actions[1]["already"] == 52
    assert [comment["issue"] for comment in kept.comments] == [52]
    assert kept.new_root is None, "a root naming a department that does not exist"
    # Five refusals: the child parent, the made-up parent, the department, the
    # person, the closed `already`, the comment, and the root. Named, not lost.
    assert len(kept.refused) == 7, kept.refused
    assert any("#52" in line and "not one of the open roots" in line
               for line in kept.refused), kept.refused


def _with_board_writes_off_a_meeting_files_nothing_and_says_so() -> None:
    """The kill switch has to reach the report, not just the write.

    `ASSISTANT_GITHUB_WRITE=0` makes `github_act` refuse every call, and refusals
    come back as text rather than exceptions. So the filing code has to read
    them: a run that opened nothing because writes are off must say that, or
    the person who pressed the button reads "put nothing on the board" and
    goes looking for a meeting with no action points in it.
    """
    filing = importlib.import_module(
        "apps.assistant.core.notulen.file_minutes"
    )
    from apps.assistant.core.notulen.decide_placements import Placements

    refusal = "refused: ASSISTANT_GITHUB_WRITE is off, so I can't change the board"
    real_execute = filing.github_act.execute
    filing.github_act.execute = lambda tool_input, actor="assistant": refusal
    try:
        filed = filing.Filed()
        plan = Placements(
            actions=[{"title": "A task", "body": "b", "parent": 53,
                      "area": "dev", "assignee": "Alex"}],
            comments=[{"issue": 53, "body": "a decision"}],
            new_root=None,
        )
        filing._open_actions(plan, None, "https://example.invalid/m.md", filed)
        filing._leave_comments(plan, "https://example.invalid/m.md", filed)
    finally:
        filing.github_act.execute = real_execute

    assert filed.issues == [] and filed.comments == [] and filed.updated == []
    assert len(filed.problems) == 2, filed.problems
    assert all("ASSISTANT_GITHUB_WRITE" in line for line in filed.problems), (
        "the report has to carry the reason it wrote nothing, or a switched-off "
        f"{ASSISTANT_NAME} reads exactly like a meeting with nothing in it: {filed.problems}"
    )

    # And the report itself says both halves out loud.
    report = filed.as_report("A meeting")
    assert "put nothing on the board" in report and "ASSISTANT_GITHUB_WRITE" in report


# ---------------------------------------------------------------------------
# A page a sender says cannot wait.
#
# The pen has four ways to send nothing: a filed board card, a human
# suppression, the quiet-hours hold, and the model judging the batch silent.
# All four are right for this road's usual traffic and all four were wrong for
# one sender. A page saying a commit was reverted off main is somebody's work
# handed back, and such pages can go unseen: fired late in the evening straight
# into the hold, or several in one day under a single repeated subject.
#
# `must_page` is the narrow way through. These cases pin both sides of it:
# what it lets past, and what it still does not.
# ---------------------------------------------------------------------------
_EJECT_SUBJECT = "\U0001f534 [the project] auto-deploy: a commit was reverted on main"


def _a_pen(monkeypatch, tmp_path):
    """A fresh pen, the quiet-hours default in force, and the phone as a list.

    Only the outermost seam is replaced, same as the morning-gate fixture
    above: the Signal send, and the model's verdict. Every gate between them
    runs for real, because the gates are what is under test.
    """
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    from apps.assistant.core import notify_flush

    landed: list[str] = []
    monkeypatch.setattr(
        notify_flush.signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return notify_flush, landed


def _composes_to(monkeypatch, notify_flush, message: str | None) -> None:
    """Replace the model's verdict, and nothing else around it."""
    monkeypatch.setattr(
        notify_flush,
        "_compose",
        lambda pings, now: notify_flush._Decision(message=message, floor="the floor text"),
    )


def _a_page_marked_as_one_that_cannot_wait_leaves_at_two_in_the_morning(
    monkeypatch, tmp_path
) -> None:
    """Quiet hours, and it goes out anyway.

    A commit being reverted off main is the one thing on this road where the
    reader loses something by hearing it at 07:30: their work is off main NOW
    and they are usually still at the keyboard.
    """
    from apps.assistant.core import state

    notify_flush, landed = _a_pen(monkeypatch, tmp_path)
    _composes_to(monkeypatch, notify_flush, "a commit was reverted on main")
    state.enqueue_ping(
        _EJECT_SUBJECT, "the gate rejected it", "auto-deploy",
        {"must_page": "yes", "blocks_deploy": "no"},
    )

    assert notify_flush.flush_pen(_at_31(2, 0)) == "a commit was reverted on main"
    assert landed == ["a commit was reverted on main"]


def _the_same_night_without_the_mark_is_still_held(monkeypatch, tmp_path) -> None:
    """The hold is not weakened, it is stepped around by one marking.

    Without this case the one above would pass just as well if the hold had
    been deleted, and deleting it is the change nobody wants: without it one
    night can wake a person several times for things that heal by morning.
    """
    from apps.assistant.core import state

    notify_flush, landed = _a_pen(monkeypatch, tmp_path)
    _composes_to(monkeypatch, notify_flush, "the gate is red")
    state.enqueue_ping(
        "[the project] auto-deploy: gate red", "a test failed", "auto-deploy",
        {"blocks_deploy": "yes"},
    )

    assert notify_flush.flush_pen(_at_31(2, 0)) is None
    assert landed == []


def _the_second_revert_of_the_day_is_not_silenced_as_a_repeat(
    monkeypatch, tmp_path
) -> None:
    """The model judged the batch silent, and this one still goes out.

    Deliberately the SECOND page under this subject inside the window, which is
    what makes it a test of the new clause rather than of the critical floor
    beside it: that floor rescues the first word about a critical subject and
    then, correctly, stops, because a repeat is usually not news. Several
    reverts can land under this one subject. They are not a repeat; each is
    a different person's commit taken off main.
    """
    from apps.assistant.core import state

    notify_flush, landed = _a_pen(monkeypatch, tmp_path)
    _composes_to(monkeypatch, notify_flush, None)
    # Already said once inside the window, so the critical floor stands down.
    monkeypatch.setattr(state, "pen_subject_delivered", lambda subject, since: True)
    state.enqueue_ping(
        _EJECT_SUBJECT, "the gate rejected it", "auto-deploy", {"must_page": "yes"},
    )

    assert notify_flush.flush_pen(_at_31(14, 0)) == "the floor text"
    assert landed == ["the floor text"]


def _a_person_silencing_the_alert_still_wins(monkeypatch, tmp_path) -> None:
    """A sender does not get to argue with a human suppression.

    A filed card is housekeeping. This is somebody deciding they do not
    want to hear it, and a marking in a shell script does not overrule that.
    """
    from apps.assistant.core import state

    notify_flush, _landed = _a_pen(monkeypatch, tmp_path)
    monkeypatch.setattr(state, "filed_issue_for", lambda _subject: None)
    monkeypatch.setattr(state, "is_suppressed", lambda _subject: (True, "Alex muted it"))

    live, silenced = notify_flush._split_silenced(
        [{"id": 1, "subject": _EJECT_SUBJECT, "facts": {"must_page": "yes"}}]
    )
    assert not live and len(silenced) == 1


def _only_the_senders_own_field_sets_the_flag() -> None:
    """A body that talks about paging does not set it.

    The flag changes what the road DOES, so it is read off the sender's marking
    and nowhere else. Anything that is not a clear yes reads as no, which is
    the direction that loses a page rather than waking somebody over a typo.
    """
    from apps.assistant.core import ping_facts

    assert ping_facts.must_page({"must_page": "yes"}) is True
    assert ping_facts.must_page({"must_page": True}) is True
    assert ping_facts.must_page({"must_page": "no"}) is False
    assert ping_facts.must_page({}) is False
    assert ping_facts.must_page(None) is False
    assert ping_facts.must_page("must_page: yes, this cannot wait") is False


def _the_flag_never_reaches_the_model() -> None:
    """the assistant still writes the page; it just no longer decides whether to.

    Every other marked field describes the thing that happened and belongs in
    front of the model. This one is routing, and a model reading "the sender
    says this cannot wait" would be reading an instruction, not a fact.
    """
    from apps.assistant.core import ping_facts

    marking = {"must_page": "yes", "qualifier": "not an outage"}
    parsed = ping_facts.marked(ping_facts.parse(_EJECT_SUBJECT, "a body"), marking)
    assert parsed.must_page is True

    fact = ping_facts.PingFact(
        ping_id=1,
        kind="deploy",
        subject=_EJECT_SUBJECT,
        display_subject="auto-deploy: a commit was reverted on main",
        source="auto-deploy",
        severity="critical",
        observed_at="2026-09-04T20:00:00+00:00",
        parsed=parsed,
        body_complete=True,
        history=ping_facts.UNKNOWN_HISTORY,
    )
    block = ping_facts._fact_block(fact)
    assert "not an outage" in block
    assert "must_page" not in block and "cannot wait" not in block

# From the gateway fragment pins the user timezone.

from apps.assistant.workspace import fragment


def _the_gateway_fragment_pins_the_user_timezone() -> None:
    """Every clock the gateway shows the model is local wall-clock."""
    patch = fragment.render_config_patch()
    assert patch["agents"]["defaults"]["userTimezone"] == LOCAL_ZONE_NAME

# From a page and a pen message are remembered on the same local clock owner read them on.

_AFTERNOON_33 = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


_SAID = "status dashboard down since 14:12 UTC"


_READ = "16:12 local time (CEST)"


@pytest.fixture()
def wire(tmp_path, monkeypatch) -> list[str]:
    """A fresh state file, a page recipient so sends are remembered, the
    clocks open, and a Signal that accepts everything and keeps the body."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15550100010")
    monkeypatch.setenv("ASSISTANT_QUIET_HOURS", "off")
    from apps.assistant.shared import signal

    bodies: list[str] = []

    def send(subject: str, body: str, *, recipient: str | None = None) -> bool:
        bodies.append(body)
        return True

    monkeypatch.setattr(signal, "send", send)
    return bodies


def _remembered() -> str:
    from apps.assistant.core import outbound

    return outbound.recent_sent()


def _a_released_page_is_remembered_as_it_was_read(wire) -> None:
    """The held page's UTC time is local in the send and in the memory."""
    from apps.assistant.core import page_hold, state

    state.hold_page(_SAID, road="triage", subject="status dashboard")
    assert page_hold.release(_AFTERNOON_33) is not None
    assert len(wire) == 1 and _READ in wire[0], wire
    assert _READ in _remembered() and "14:12 UTC" not in _remembered()


def _a_pen_page_is_remembered_as_it_was_read(wire, monkeypatch) -> None:
    """The pen's composed page, with the model's UTC time, the same way."""
    from apps.assistant.core import notify_flush, state

    monkeypatch.setattr(
        notify_flush,
        "_compose",
        lambda pings, now: notify_flush._Decision(message=_SAID, floor=_SAID),
    )
    state.enqueue_ping("status dashboard down", "probe failed", "notify")
    assert notify_flush.flush_pen(_AFTERNOON_33) is not None
    assert len(wire) == 1 and _READ in wire[0], wire
    assert _READ in _remembered() and "14:12 UTC" not in _remembered()

# From a patrol the minutes report and a security page leave on local and the chat remembers the text that was sent.

_ALEX_34 = "+15550100012"


_UTC_LINE = "The blackbox forward hung at 14:12 UTC."


_LOCAL = "16:12 local"


_WHEN = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pod_34(tmp_path, monkeypatch):
    """A fresh state DB, a bearer, a pinned clock and a send that lands and records its text."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX_34}=Alex:founder:{_ALEX_34}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX_34)
    from fastapi.testclient import TestClient

    from apps.assistant.core import state
    from apps.assistant.gates import app as gate_app
    from apps.assistant.shared import local_time

    state.reset_for_tests()
    sent: list[str] = []
    real_in_local_time = local_time.in_local_time
    monkeypatch.setattr(local_time, "in_local_time", lambda text, now=None: real_in_local_time(text, now or _WHEN))

    def land(body: str) -> bool:
        sent.append(body)
        return True

    monkeypatch.setattr(gate_app, "_send_beat", land)
    return SimpleNamespace(client=TestClient(gate_app.app), app=gate_app, sent=sent, state=state)


def _remembered_last() -> str:
    from apps.assistant.core import sent_feed

    return sent_feed.sends_after(0).sends[-1]["text"]


def _a_patrol_line_leaves_on_local_time(pod_34, monkeypatch) -> None:
    """The patrol line the owner reads and the copy the chat keeps both say 16:12 local."""
    monkeypatch.setattr(pod_34.app.openclaw_issue_sweep, "sweep_orphan_issues", lambda: [])
    monkeypatch.setattr(pod_34.app.openclaw_recurring, "file_recurring_observations", lambda: [])
    monkeypatch.setattr(
        pod_34.app.openclaw_patrol, "patrol",
        lambda: SimpleNamespace(text=_UTC_LINE, worklist_items=[]),
    )
    response = pod_34.client.post("/webhook/patrol", headers={"Authorization": f"Bearer {_SECRET}"})
    assert response.status_code == 200, response.text
    assert pod_34.sent and _LOCAL in pod_34.sent[-1] and "UTC" not in pod_34.sent[-1], pod_34.sent
    assert _remembered_last() == pod_34.sent[-1]


def _the_minutes_report_leaves_on_local_time(pod_34, monkeypatch) -> None:
    """The minutes report is rewritten before it is sent and remembered."""
    filed = SimpleNamespace(
        issues=[], root=None, updated=[], comments=[], problems=[],
        as_report=lambda title: f"Minutes of {title} filed. {_UTC_LINE}",
    )
    monkeypatch.setattr(pod_34.app.openclaw_notulen, "file_minutes", lambda *args: filed)
    response = pod_34.client.post(
        "/webhook/notulen",
        headers={"Authorization": f"Bearer {_SECRET}"},
        json={"job_id": "j1", "title": "Alex & Sam", "meeting_date": "2026-10-22", "markdown": "# notes"},
    )
    assert response.status_code == 200, response.text
    assert pod_34.sent and _LOCAL in pod_34.sent[-1] and "UTC" not in pod_34.sent[-1], pod_34.sent
    assert _remembered_last() == pod_34.sent[-1]


def _a_security_page_leaves_on_local_time(pod_34, monkeypatch) -> None:
    """The security judgement's page is rewritten before it is sent and remembered."""
    from apps.assistant.core import security_sweep

    captured: list[str] = []
    monkeypatch.setattr(security_sweep.state, "count_since", lambda kind, minutes: 50)
    monkeypatch.setattr(security_sweep.state, "should_page", lambda key, seconds: True)
    monkeypatch.setattr(security_sweep.state, "recent_security_events", lambda minutes: [])
    monkeypatch.setattr(security_sweep._judge, "judge_security", lambda *args: _UTC_LINE)
    monkeypatch.setattr(
        security_sweep._signal, "send",
        lambda subject, body: captured.append(body) or True,
    )
    security_sweep.sweep_security()
    assert captured and _LOCAL in captured[-1] and "UTC" not in captured[-1], captured
    assert _remembered_last().endswith(captured[-1]), "the chat keeps a different text than was sent"


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_covering_page_triage_reads_off_the_awareness_rows_is_one_the_claim_gate_can_find),
    *_cases(_a_critical_leaves_inside_the_hold_and_the_warning_waits, ("hour", "minute"), [(2, 0), (7, 45)]),
    *_cases(_a_warning_alone_is_still_held_through_the_night),
    *_cases(_a_critical_whose_alert_resolved_is_still_dropped),
    *_cases(_an_outage_costs_a_send_per_backoff_step_not_per_pass),
    *_cases(_the_late_message_says_so_and_the_next_outage_starts_short),
    *_cases(_a_card_filed_off_the_bare_spelling_mutes_the_marked_ping),
    *_cases(_a_row_stored_with_a_marker_is_found_and_lifted_by_any_spelling),
    *_cases(_a_subject_critical_in_one_spelling_is_never_filed),
    *_cases(_a_page_whose_alert_resolved_before_it_left_is_dropped),
    *_cases(_a_flap_is_still_firing_and_still_pages),
    *_cases(_a_page_saying_the_thing_came_back_is_not_stale),
    *_cases(_one_firing_episode_pages_once_and_a_new_one_pages_again),
    *_cases(_a_page_with_no_fingerprint_is_never_dropped),
    *_cases(_the_brief_carries_what_it_names_and_the_rest_still_leaves),
    *_cases(_with_no_brief_the_night_leaves_when_the_wait_runs_out),
    *_cases(_a_saturday_night_leaves_at_eight),
    *_cases(_the_pens_night_page_is_carried_only_when_the_brief_names_each_subject, 
    ("brief", "sent"),
    [
        ("Overnight: auto-deploy: gate red on main, 02:10.", [_PEN_PAGE]),
        (
            "Overnight: auto-deploy: gate red on main, 02:10; "
            "batch done [nightly], 22:03.",
            [],
        ),
    ],
),
    *_cases(_a_lifted_mute_is_not_refiled_from_the_rows_that_filed_it),
    *_cases(_a_lapsed_mute_is_not_refiled_from_the_rows_before_it_lapsed),
    *_cases(_a_stripped_command_takes_its_lead_in_and_its_next_step_with_it),
    *_cases(_a_dropped_line_leaves_one_blank_line_not_two),
    *_cases(_a_read_only_command_line_goes_with_its_lead_in),
    *_cases(_a_message_with_nothing_stripped_is_left_alone),
    *_cases(_triage_never_shows_the_model_the_first_action_command),
    *_cases(_the_alerts_pointer_to_its_evidence_reaches_the_model),
    *_cases(_a_unit_nothing_read_is_asked_about_then_left_out),
    *_cases(_a_repair_nothing_backs_is_asked_about_then_left_out),
    *_cases(_the_pods_voice_no_longer_teaches_giving_up_on_the_journal),
    *_cases(_hyphenated_english_before_service_is_not_a_unit, 
    "sentence",
    [
        "Webapp is down; the health-check service answers 502.",
        "The third-party service is slow.",
        "It is a long-running service.",
    ],
),
    *_cases(_a_true_page_keeps_its_symptom_line_about_a_hyphenated_service),
    *_cases(_a_dropped_page_says_it_was_never_sent_and_why),
    *_cases(_a_waiting_page_says_it_has_not_gone_yet),
    *_cases(_a_page_that_was_never_queued_says_not_delivered),
    *_cases(_a_filed_silence_names_its_cards),
    *_cases(_a_suppressed_silence_names_the_suppression),
    *_cases(_each_closed_card_is_one_line_and_the_open_one_is_not_named),
    *_cases(_github_is_asked_once_and_the_mute_still_stands),
    *_cases(_the_brief_reads_it_through_my_actions),
    *_cases(_a_resolve_inside_the_dedup_window_of_a_delivered_page_is_an_all_clear),
    *_cases(_a_resolve_of_a_firing_nobody_heard_about_stays_silent),
    *_cases(_the_all_clear_never_reads_as_the_next_episodes_page),
    *_cases(_a_second_finding_is_not_called_a_repeat),
    *_cases(_each_finding_names_its_own_commit),
    *_cases(_a_gate_red_repeat_still_escalates_and_prints_no_sha),
    *_cases(_every_send_from_outside_the_recipients_session_is_in_the_feed_with_their_number),
    *_cases(_nothing_comes_back_past_the_last_send_returned),
    *_cases(_a_cover_described_in_prose_is_asked_for_and_then_stands),
    *_cases(_with_nothing_delivered_or_queued_it_pages_without_asking),
    *_cases(_a_silence_saying_the_condition_resolved_is_not_a_page_claim),
    *_cases(_a_queued_cover_takes_the_silenced_fingerprint_along_when_it_leaves),
    *_cases(_a_raw_page_does_not_stop_the_checked_page_written_after_it),
    *_cases(_a_resend_whose_own_page_is_queued_stays_silent_and_keeps_that_page),
    *_cases(_a_page_written_in_answer_to_the_cover_question_passes_the_draft_checks),
    *_cases(_a_repage_inside_the_window_folds_and_one_after_it_goes),
    *_cases(_a_spelled_out_issue_is_a_citation),
    *_cases(_an_issue_no_reading_carried_is_asked_about_then_left_out),
    *_cases(_an_issue_a_reading_carried_stays),
    *_cases(_a_diagnosis_by_analogy_to_a_past_incident_is_left_out),
    *_cases(_the_pass_leaves_its_readings_and_its_reason_on_the_loop_triage),
    *_cases(_a_critical_silenced_on_a_stamp_nothing_read_pages),
    *_cases(_a_critical_silenced_on_a_stamp_a_reading_carries_stays_silent),
    *_cases(_a_claimed_page_on_a_fingerprint_that_never_delivered_pages),
    *_cases(_a_claimed_page_that_was_delivered_stands_with_the_time_code_read),
    *_cases(_cover_by_another_page_stands_only_when_that_page_was_delivered),
    *_cases(_the_awareness_rows_tell_two_alerts_of_one_name_apart),
    *_cases(_the_stored_reason_keeps_the_models_clock_times),
    *_cases(_the_page_history_gives_local_time_and_a_counted_total),
    *_cases(_an_all_clear_says_when_the_alert_stopped_and_never_that_the_problem_is_gone),
    *_cases(_the_summariser_sees_the_fix_commit),
    *_cases(_the_window_bound_reaches_github_as_utc_with_a_z),
    *_cases(_a_cut_commit_list_is_not_read_as_no_resolution),
    *_cases(_the_summariser_is_told_to_keep_hedges),
    *_cases(_a_page_about_an_open_item_concerns_the_id_the_model_read_in_its_turn),
    *_cases(_an_id_no_open_item_has_is_dropped),
    *_cases(_a_page_about_item_36_reaches_the_relay_marked_as_concerning_36),
    *_cases(_a_page_that_names_no_item_concerns_nothing),
    *_cases(_the_question_reaches_the_relay_concerning_the_item_it_filed),
    *_cases(_one_cause_is_one_model_call_and_one_held_page),
    *_cases(_a_resend_in_another_order_folds_into_the_same_held_page),
    *_cases(_every_fingerprint_of_the_cause_reads_delivered_once_the_page_lands),
    *_cases(_the_leader_recovering_alone_does_not_drop_the_group_page),
    *_cases(_every_house_rule_reaches_assistants_voice),
    *_cases(_the_two_swaps_are_the_only_ones),
    *_cases(_the_soul_still_carries_exactly_one_english_only_rule),
    *_cases(_a_worklist_item_assistant_opens_itself_is_recorded_as_assistants),
    *_cases(_a_message_assistant_starts_itself_is_held_by_quiet_hours),
    *_cases(_a_board_write_booked_to_assistant_reaches_github_act),
    *_cases(_naming_assistant_still_cannot_create_a_video_call),
    *_cases(_every_utc_shape_is_written_on_locals_summer_clock),
    *_cases(_a_utc_time_after_the_change_is_written_on_the_winter_clock),
    *_cases(_on_the_day_of_the_change_each_time_takes_its_own_offset),
    *_cases(_a_range_marked_utc_once_moves_both_ends_and_keeps_its_length),
    *_cases(_a_link_or_code_span_in_the_message_passes_through_byte_for_byte),
    *_cases(_a_dated_stamp_from_another_day_keeps_its_date),
    *_cases(_a_time_the_model_already_converted_is_said_once),
    *_cases(_a_time_naming_no_zone_or_another_offset_is_left_alone),
    *_cases(_the_send_seam_rewrites_a_person_page_and_passes_a_machine_page_through),
    *_cases(_a_booking_assistant_never_made_is_caught_before_it_is_confirmed),
    *_cases(_the_same_confirmation_passes_once_the_write_really_landed),
    *_cases(_one_receipt_cannot_back_a_claim_about_two_writes),
    *_cases(_a_line_written_to_one_teammate_is_held_back_from_another_phone),
    *_cases(_a_recipient_the_registry_cannot_place_counts_as_the_wrong_reader),
    *_cases(_a_deploy_sha_in_a_message_is_caught_as_assistants_own_bookkeeping),
    *_cases(_a_long_message_is_split_to_fit_and_loses_not_one_word),
    *_cases(_a_message_that_already_fits_goes_out_as_one_piece),
    *_cases(_a_night_of_pings_and_a_held_beat_reach_the_phone_as_one_message),
    *_cases(_a_patrol_finding_in_the_night_is_held_and_arrives_in_the_morning),
    *_cases(_a_night_nobody_reports_on_still_reaches_the_phone),
    *_cases(_the_morning_gate_holds_nothing_outside_the_morning),
    *_cases(_nothing_is_marked_sent_when_the_send_failed),
    *_cases(_the_pen_queues_its_night_page_instead_of_sending_it_at_half_seven),
    *_cases(_a_page_says_the_time_and_not_the_date_it_is_read_on),
    *_cases(_a_stamp_from_another_day_keeps_its_date),
    *_cases(_a_count_is_said_in_words_or_not_at_all),
    *_cases(_the_unit_is_not_said_twice_when_the_subject_already_names_it),
    *_cases(_two_pings_arriving_together_are_one_sentence),
    *_cases(_riders_at_different_moments_are_not_folded_together),
    *_cases(_how_many_issues_a_meeting_opens_is_read_and_not_judged),
    *_cases(_a_meeting_can_only_land_on_something_that_is_open),
    *_cases(_assistant_cannot_open_a_root_without_saying_what_it_checked),
    *_cases(_work_the_board_already_carries_is_not_opened_a_second_time),
    *_cases(_an_action_point_that_is_neither_new_nor_known_is_left_off),
    *_cases(_the_question_alex_had_already_answered_is_not_asked_again),
    *_cases(_a_second_message_that_carries_something_new_still_goes),
    *_cases(_a_message_too_short_to_judge_is_never_called_a_repeat),
    *_cases(_the_second_relay_never_reaches_the_phone),
    *_cases(_a_new_question_after_a_refusal_still_goes_out),
    *_cases(_every_webhook_can_actually_reach_the_work_it_names),
    *_cases(_the_board_is_read_in_pages_github_will_actually_serve),
    *_cases(_only_a_root_is_offered_as_a_parent),
    *_cases(_a_choice_outside_what_was_offered_is_dropped_not_written),
    *_cases(_with_board_writes_off_a_meeting_files_nothing_and_says_so),
    *_cases(_a_page_marked_as_one_that_cannot_wait_leaves_at_two_in_the_morning),
    *_cases(_the_same_night_without_the_mark_is_still_held),
    *_cases(_the_second_revert_of_the_day_is_not_silenced_as_a_repeat),
    *_cases(_a_person_silencing_the_alert_still_wins),
    *_cases(_only_the_senders_own_field_sets_the_flag),
    *_cases(_the_flag_never_reaches_the_model),
    *_cases(_the_gateway_fragment_pins_the_user_timezone),
    *_cases(_a_released_page_is_remembered_as_it_was_read),
    *_cases(_a_pen_page_is_remembered_as_it_was_read),
    *_cases(_a_patrol_line_leaves_on_local_time),
    *_cases(_the_minutes_report_leaves_on_local_time),
    *_cases(_a_security_page_leaves_on_local_time),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_page_reaches_a_person_only_as_news_backed_by_the_assistants_own_reads_on_their_local_clock_and_every_send_is_relayed_once(scenario, given, uses, request):
    """A page reaches a person only when it is news, carries only what the assistant's own reads back, is written on that person's local clock, and every send is remembered and relayed once: every row of CASES must hold, each on the frozen clock."""
    request.getfixturevalue("frozen_clock")
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
