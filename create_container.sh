#!/bin/bash
cd $(dirname ${0})
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
    --restart unless-stopped \
    ubuntu_supervisor:18.04
