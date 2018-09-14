#!/bin/bash
. ./bash/preambule.sh

docker stop phabricator
docker rm phabricator
