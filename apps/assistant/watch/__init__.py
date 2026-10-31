"""Everything that watches the assistant from outside its container.

Nothing inside a container can tell you the container is gone, so these
passes run on the server as systemd timers and answer one question between
them: is the assistant alive and doing its job?

Module map (one public concern per file):

    door.py         `door_url()`: where a pass on the server reaches the door.
    trigger.py      `trigger(path)`: POST one of the door's bearer-gated webhook
                    routes so the door runs that pass. The subcommand argument
                    picks the route.
    heartbeat.py    `post_heartbeat(name)`: beat one stack component that a
                    caller just proved alive (the Signal send canary).
    chat_relay.py   copy the assistant's outside sends into the recipient's own
                    gateway session, so a reply in chat has the context.
    claim_audit/    the weekly check that what the assistant SAID was backed by
                    what it could see.
    run.py          `main(argv)`: which pass runs, and the exit contract each
                    one keeps. Read its header before changing an exit code.

NO RE-EXPORTS of the pass callables: the systemd units are the callers and
they arrive through `__main__`.

FAILURE POLICY: per pass, and they disagree on purpose. `run.py`'s header is the
list.
"""
