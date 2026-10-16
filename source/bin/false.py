"""false - do nothing, unsuccessfully ($? = 1). Useful in scripts and with && / ||."""

import shell


def run(args, cwd):
    shell._set_status(1)
