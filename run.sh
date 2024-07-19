#!/bin/bash

# Load pyenv automatically
export PATH="/home/nova/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv virtualenv-init -)"

# Activate the desired pyenv environment
pyenv activate 2wsync

# Run the Python script
python 2wsync.py -v start
