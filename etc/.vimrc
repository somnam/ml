set mouse=
set t_Co=256
syntax on " Syntax highlight by default on.
filetype plugin on " Load filetype specific plugins
filetype indent on " Load filetype specific indentation rules
set autoindent smartindent " Set indentation
set shiftwidth=4 tabstop=4 softtabstop=4 expandtab smarttab " Tab Handling
set number " Show line numbers
set showcmd " Show command in bottom bar
set wildmenu wildmode=full:longest " Visual autocomplete for command menu
set lazyredraw " Redraw only when necessary, speeds up macros
set laststatus=2 " Always display statusbar
set incsearch " Incremental search
set showmatch " Show matching brackets
" Set more readable diff colors in terminals
highlight CursorColumn term=reverse ctermbg=8
highlight DiffAdd      term=bold ctermfg=42 ctermbg=24
highlight DiffDelete   term=bold ctermfg=42 ctermbg=24
highlight DiffChange   term=bold ctermfg=42 ctermbg=24
highlight DiffText     term=bold ctermfg=42 ctermbg=126
