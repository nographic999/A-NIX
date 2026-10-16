"""help - quick one-line-per-command reference (see `man` for detail,
`man <command>` jumps straight to one command).
"""

import shell

_TEXT = """Builtins:
  cd [path]  pwd  exit (restart shell)  source|. <file.sh>  read [VAR]
  echo [text]  export [KEY[=VAL]]  unset <KEY>  let VAR=expr
  alias [name=cmd]  unalias <name>  history [N|-c]  !! !N !text
  time <cmd>   cmd &  (background job)  jobs [-f]  kill
  spawn <file.py> [args]  tasks [log]  stop <N|all>   (async tasks, core 1)
  $VAR ${VAR} $? $((expr)) $(command)   $1..$9 $# $@ in scripts
  "quotes" group words   cmd 2> file   cmd 2>&1   > /dev/null
  cmd > file  cmd >> file  cmd < file  cmd1 | cmd2   Ctrl-C stops a command
  a ; b (both)  a && b (b if a worked)  a || b (b if a failed)
  Up/Down history, Tab completes, Ctrl-C at the prompt -> REPL
Files:
  ls [-l] [path...]   tree [path]   find [path] ["pattern"]
  cat <file...>   head|tail [-n N|-N] <file>   wc <file...>   pg <file>
  grep [-i -v -n -c -q] "text" <file...>   hexdump [-s N] [-n N] <file>
  sort [-r -n -u]  uniq [-c]  cut -f|-c LIST [-d SEP]  ... | tee [-a] <file>
  replace [-i] "old" "new" [file]
  cp [-r] <src...> <dst>   mv <src...> <dst>   rm [-r] <file...>
  mkdir <dir...>  rmdir <dir...>  touch <file...>  sha256 <file> [sum]
  diff <f1> <f2>  edit <file> (^H: keys)
  df [-b] [path]  du [-s|-a] [path]  stat <path>  which <cmd>  mkfs [-a]
  seq [first [step]] last   true  false
  log [-n] <file> [values]   plot [-f N] [-d SEP] [-h ROWS] [-b] [file]
System:
  uname  ps  date [ntp]  free [-b|-m]  sleep [-l|-d] <s>  watch <s> <cmd>
  dmesg [-c]  selftest [-q]  reboot [-s]  wdt start|feed|status
  conf [KEY [VALUE]]   settings in /etc/anix.conf (WiFi, colours, RAM, watchdog...)
  cron [log [N] | run N | reload | on | off]   (jobs in /etc/crontab)
  run <file> [args]   python
  choice [opts]  whiptail ...  help  man [topic]  license  clear  temp
Hardware:
  out <pin>|LED <0|1>   in <pin>|LED [up|down|none]   pins
  in -w <pin> [up|down|none] [rise|fall|any] [-t s]   wait for a change
  adc <26-28>   pwm <pin> <0-100>|off [hz]
  i2c scan [sda scl] | read <addr> <reg|-> [n] | write <addr> <reg|-> <hex>
  uart <bus> init [baud] [tx] [rx] | send [-crlf|-cr|-lf|-hex] <text>
       | recv [ms] [-hex]          uartterm <bus> [baud] [crlf]
  spi <bus> init [baud] [sck] [mosi] [miso] [cs] | xfer|write <hex> | read <n>
  flash id|status|unprotect|read|write|erase|save|load   (SPI NOR, see man)
Network (W boards):
  wifi [-r N] [ssid [pw]] | status | off   scan   ping <host>[:port] [n]
  curl <url>   wget <url> [file]   httpd [-p pw] [pins...] | status | stop  (+ files)
  ble scan|advertise|status|off
  telnetd [-p pw] [port] | status | stop   (console over Wi-Fi)
  nc [-crlf] <host> <port> | nc -l <port> | nc -u <host> <port> [text]
  nc -l <port> -o <file> (receive)  |  -i <file> (send)   any file, raw
A bare name runs <name>.sh, .py or .mpy from cwd, then $PATH.
Commands that read text (cat grep head tail wc sort uniq cut replace
hexdump sha256) read the pipe when given no file: ls | grep txt"""


def run(args, cwd):
    shell._out(shell._banner())
    for line in _TEXT.split("\n"):
        shell._out(line)
