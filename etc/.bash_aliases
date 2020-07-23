#############################################################################

export PS1="\\[\e[0;32m\]\u@\h\[\e[m\] \\[\e[1;32m\]\w\[\e[m\] \$ "
umask 022

# Update window size after every command
shopt -s checkwinsize

# Bindings for interactive shell.
if [[ "$-" =~ "i" ]]; then
    # Enable history expansion with space
    # E.g. typing !!<space> will replace the !! with your last command
    bind Space:magic-space
    # Perform file completion in a case insensitive fashion
    bind "set completion-ignore-case on"
    # Treat hyphens and underscores as equivalent
    bind "set completion-map-case on"
    # Display matches for ambiguous patterns at first tab press
    bind "set show-all-if-ambiguous on"
    # Immediately add a trailing slash when autocompleting symlinks to directories
    bind "set mark-symlinked-directories on"
    # Enable incremental history search with up/down arrows (also Readline goodness)
    # Learn more about this here: http://codeinthehole.com/writing/the-most-important-command-line-tip-incremental-history-searching-with-inputrc/
    bind '"\e[A": history-search-backward'
    bind '"\e[B": history-search-forward'
    bind '"\e[C": forward-char'
    bind '"\e[D": backward-char'
fi

#############################################################################

export EDITOR="vim"

# Append to the history file, don't overwrite it
shopt -s histappend

# Save multi-line commands as one command
shopt -s cmdhist

# Record each line as it gets issued
PROMPT_COMMAND='history -a'

# Huge history. Doesn't appear to slow things down, so why not?
HISTSIZE=500000
HISTFILESIZE=100000

# Avoid duplicate entries
HISTCONTROL="erasedups:ignoreboth"

# Don't record some commands
export HISTIGNORE="&:[ ]*:exit:ls:bg:fg:history:clear"

# Use standard ISO 8601 timestamp
# %F equivalent to %Y-%m-%d
# %T equivalent to %H:%M:%S (24-hours format)
HISTTIMEFORMAT='%F %T '

export LS_OPTIONS='--color=auto -h'

#############################################################################

alias ls='ls $LS_OPTIONS'
alias ll='ls $LS_OPTIONS -l'
alias l='ls $LS_OPTIONS -lA'

#############################################################################
