#!/bin/bash
cd $(dirname ${0})
. ./bash/preambule.sh

docker stop phabricator
docker rm phabricator
