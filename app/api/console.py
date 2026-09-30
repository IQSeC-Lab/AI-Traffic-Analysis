"""
Printing to the API server's console.

The console can go away while the server keeps running, e.g. when the SSH session
that started `npm run dev` drops: printing then raises BrokenPipeError. That must
never stop a run or a download, so everything prints through here.
"""


def console(msg: str) -> None:
    try:
        print(msg, flush=True)
    except (OSError, ValueError):   # broken pipe, hung-up terminal, closed stdout
        pass
