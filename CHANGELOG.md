# Changelog

## 0.1T

First public version. Runs on Pico, Pico W, Pico 2 and Pico 2 W with
MicroPython 1.29.

### Shell

- builtins: cd pwd echo export unset let read exit (restarts the
  shell) alias unalias history time source / .
- prompt with line editing, history (Up/Down, `history`, !! !N !text)
  and Tab completion; history kept in /var/history
- pipes `a | b | c`, `a ; b`, `a && b`, `a || b`
- redirects `>` `>>` `<` `2>` `2>>` `2>&1`, /dev/null; `>` writes safely
  (temp file, renamed when done); `>>` adds a missing line break first
- variables, $VAR ${VAR} $? $((expr)) $(command), quotes, globs
- aliases (`ed` = edit, `restart` = reboot, `ll`, `..` in /etc/profile)
- background job `cmd &` with jobs / kill (core 1); its output appears
  above the prompt
- task scheduler: spawn / tasks / stop - several async programs on
  core 1
- core 1 runs one program at a time (a job, the tasks or your own,
  via /lib/core1.py); before starting, A-NIX checks that a free RAM
  block for its stack exists (16, 12 or 8 KB), so MicroPython 1.29's
  bug - a failed start blocking core 1 until reset - can't happen
- job and task output goes through RAM; only core 0 writes the logs,
  and loading commands on core 1 takes turns with core 0's log and
  history writes (a lock), so the two cores never use the filesystem
  at the same moment
- .py and compiled .mpy programs run like commands; a bare name runs
  name.sh, .py or .mpy from the folder, then $PATH
- only /lib is on the import path: a file in /bin or the current
  folder can't hide a library
- Ctrl-C stops a command; at an empty prompt it leaves to the
  MicroPython REPL (for Thonny / mpremote)
- rarely used parts load only when needed and leave RAM again when it
  runs low; the prompt shows (low RAM)

### Scripts

- if / elif / else, for, while, break, continue, functions, goto,
  arguments $1..$9 $# $@, read, choice, whiptail dialogs
- /etc/startup runs at every shell start; /etc/crontab runs jobs
  (@boot, every N s/m/h/d up to 6 days, at HH:MM) with `cron log`,
  `cron run N`, `cron reload`
- nested scripts stop at 10 levels with a clear error

### Commands (79)

- files: ls tree cat head tail wc grep sort uniq cut diff find cp mv
  rm mkdir rmdir touch stat du df which tee replace hexdump sha256 pg
  seq log plot edit mkfs
- system: ps free uname date (ntp) sleep (-l light, -d deep) watch
  dmesg selftest reboot wdt conf cron run python help man license
  clear temp true false
- jobs and tasks: jobs kill spawn tasks stop
- scripts: choice whiptail
- hardware: out in (-w wait for a change) pins adc pwm i2c spi uart
  uartterm flash (SPI NOR)
- network (W boards): wifi (-r N retries) scan ping curl wget nc
  (also file transfer) httpd telnetd ble
- wget streams to flash: the size is limited by free flash, not RAM

### Editor

- `edit`: nano-like keys, files up to EDIT_MEM % of free RAM (bigger
  ones with `pg`), undo, find, goto line, mark/copy/paste,
  auto-indent; syntax colours for .py, .sh, /etc/startup,
  /etc/crontab, .conf/.cfg/.ini and /etc/profile

### Network

- telnetd and httpd both run on core 0 and together: the prompt
  answers them while it waits for keys, and core 1 stays free
- telnetd: the console over WiFi for PuTTY (Telnet); password from -p
  or TELNET_PASS; one client, replaced when idle
- httpd: web panel for pins (outputs, PWM, inputs, ADC) and a file
  browser for the whole filesystem (download, view, upload, new
  folder, rename, delete); WEB_PINS=none gives only the file browser;
  password required; changes accepted only from the panel's own pages

### Colours

- like a Linux terminal: start-up banner, prompt, ls / tree like
  dircolors, grep matches, diff, error:, dmesg, selftest, cron, jobs,
  tasks, wifi, pins, man headings - only on the screen, never in a
  file, pipe or log; `conf COLOR off` for a plain terminal

### Robustness

- boot.py drives every output pin low at each start; `exit` keeps the
  pins as they are
- BOOTSEL safe mode: held at start, the shell starts without
  /etc/profile, /etc/startup, /etc/crontab and the watchdog
- boot log (dmesg): boot number, time, cause, mode
- optional watchdog (WATCHDOG, WATCHDOG_HANG): boot.py starts and
  feeds it at every start, so uploads from the PC, Thonny and
  mpremote keep working with WATCHDOG=on; a frozen board resets
- settings in /etc/anix.conf, changed with `conf` (WiFi, passwords,
  pins, colours, logs, RAM, watchdog); PATH, HOME and aliases in
  /etc/profile
- free shows the largest free block too (what one big allocation can
  get when RAM is fragmented); free -m shows a map of the RAM
- cron logs only failed jobs by default (CRON_LOG=errors), so a job
  every minute doesn't write the flash every minute
- PROFILE, STARTUP, CRONTAB, HISTORY on/off in anix.conf: switch off what you
  don't use, so it isn't loaded at all
- less fragmented RAM after start: settings, crontab and history read
  one line at a time (comments cost no RAM), gc.collect() before each
  part that stays in RAM
- logs trimmed by size (LOG_MAX); uptime correct past 12.4 days
- low RAM (MEM_LOW): big unused modules (editor, script, syntax ...)
  are unloaded biggest first, only until enough is free; the small,
  often used ones stay - fewer unload/reload cycles, fewer holes in RAM
- out-of-range values (pins, times, sizes) give a message, not a crash
- selftest checks the chip, RAM, flash, clock, GPIO, every module and
  command, the /etc files, the manual and the license
- full manual on the board: `man`, `man <command>`

### PC tools

- menu.sh (Linux: Debian, Ubuntu, Raspberry Pi OS) and menu.bat, both
  driving anix.py: install A-NIX (.mpy or .py), copy /root (.py
  compiled to .mpy on the way - less RAM on the board), backup,
  install MicroPython (.uf2), nuke, console over USB, console over
  WiFi (telnet), find the board on WiFi
- a status line shows where the Pico is (USB / BOOTSEL / not found)
- menu.sh sets itself up: Python environment in .venv, folder
  permissions, dialout group (asks first); `menu.sh uninstall`
  removes it again
- missing Python packages are offered for installing; a busy USB port
  or a board in BOOTSEL mode is explained; the board restarts by
  itself after an install

### Known issues

- a program's OWN file reads and writes on core 1 (a `cmd &` job
  running cat, wget or >, your own core-1 program) are not covered by
  A-NIX's lock: keep core-1 programs off files while core 0 uses them
- httpd answers only while the prompt waits - not while a command runs;
  a big file transfer holds the prompt for its few seconds
- not yet tested on real hardware: Pico 2 / Pico 2 W specifics, light
  and deep sleep, the watchdog reset path
