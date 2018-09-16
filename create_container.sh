#!/bin/bash
. ./bash/preambule.sh

if [ ! "$(docker network ls | grep phabricator_net)" ]; then
    docker network create \
        --subnet 172.19.0.0/16 \
        phabricator_net
fi

docker run \
    --detach \
    --interactive \
    --name=phabricator \
    --ip=172.19.0.5 \
    --publish 80:80 \
    --network=phabricator_net \
    ubuntu:18.04
