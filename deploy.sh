#!/bin/bash
. ./bash/preambule.sh

# Run the deployment script.
source ./.venv/bin/activate
python3 deploy.py 'phabricator.install()'
