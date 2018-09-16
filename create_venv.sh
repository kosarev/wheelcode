#!/bin/bash
cd $(dirname ${0})
. ./bash/preambule.sh

# Create virtual environment.
python3 -m venv .venv

# Install depencencies.
source ./.venv/bin/activate
pip install --upgrade wheel  # Needs to be installed before others.
pip install --upgrade paramiko
